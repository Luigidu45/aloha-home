# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline VLM in an owned process: one job, hard deadline, no actuator access."""

import hashlib
import io
import json
import multiprocessing as mp
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
import resource
import time
from typing import Any

import numpy as np
from PIL import Image as PILImage

from dimos.experimental.household_assistant.planner_contracts import (
    BackendReply,
    PixelReceipt,
    PlannerConfig,
)
from dimos.experimental.household_assistant.planner_grammar import decision_parser
from dimos.experimental.household_assistant.planner_options import (
    missing_request_slots,
    needs_visual_clarification,
)
from dimos.experimental.household_assistant.visual import ObservedView
from dimos.msgs.sensor_msgs.Image import Image


def pack_image(view: ObservedView, image: Image) -> dict[str, Any]:
    view.validate_image(image)
    stream = io.BytesIO()
    PILImage.fromarray(image.to_rgb().data).save(stream, format="PNG")
    return {"view_id": view.id, "rgb_sha256": view.rgb_sha256, "png": stream.getvalue()}


def model_worker(connection: Connection, config: PlannerConfig, model_path: str) -> None:
    # Heavy optional libraries load exclusively inside the inference process.
    from lmformatenforcer.characterlevelparser import StringParser, UnionParser
    from lmformatenforcer.integrations.transformers import (
        build_token_enforcer_tokenizer_data,
        build_transformers_prefix_allowed_tokens_fn,
    )
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    try:
        torch.set_num_threads(config.cpu_threads)
        processor = AutoProcessor.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=False,
            min_pixels=56 * 56,
            max_pixels=config.max_pixels,
        )
        model = (
            AutoModelForImageTextToText.from_pretrained(
                model_path,
                local_files_only=True,
                trust_remote_code=False,
                torch_dtype=getattr(torch, config.dtype),
                attn_implementation="sdpa",
            )
            .to(config.device)
            .eval()
        )
        tokenizer_data = build_token_enforcer_tokenizer_data(processor.tokenizer)
        connection.send({"ready": True})
        while True:
            job = connection.recv()
            if job is None:
                return
            started = time.monotonic()
            images = []
            receipts = []
            content = []
            for payload in job["images"]:
                with PILImage.open(io.BytesIO(payload["png"])) as source:
                    image = source.convert("RGB")
                rgb = np.asarray(image)
                digest = hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()
                if digest != payload["rgb_sha256"]:
                    raise ValueError("received PNG differs from declared RGB evidence")
                images.append(image)
                receipts.append(
                    {
                        "view_id": payload["view_id"],
                        "rgb_sha256": digest,
                        "png_sha256": hashlib.sha256(payload["png"]).hexdigest(),
                    }
                )
                content.extend(
                    [
                        {"type": "text", "text": "Image ID: " + payload["view_id"]},
                        {"type": "image"},
                    ]
                )
            # A short visual inspection prevents the language instruction from
            # overwhelming the image. Same real VLM, pixels only, no scene labels.
            vision_prompt = "How many bottles are clearly visible in this image? Answer exactly 0, 1, 2 (two or more), or unknown if the scene is obstructed. A cup is not a bottle."
            vision_messages = [
                {"role": "user", "content": [*content, {"type": "text", "text": vision_prompt}]}
            ]
            vision_inputs = processor(
                text=[
                    processor.apply_chat_template(
                        vision_messages, add_generation_prompt=True, tokenize=False
                    )
                ],
                images=images,
                return_tensors="pt",
            ).to(device=config.device, dtype=getattr(torch, config.dtype))
            vision_length = vision_inputs["input_ids"].shape[1]
            vision_grammar = build_transformers_prefix_allowed_tokens_fn(
                tokenizer_data,
                UnionParser([StringParser(value) for value in ("0", "1", "2", "unknown")]),
            )
            with torch.inference_mode():
                vision_output = model.generate(
                    **vision_inputs,
                    max_new_tokens=8,
                    do_sample=False,
                    prefix_allowed_tokens_fn=vision_grammar,
                )
            vision_tokens = vision_output[:, vision_length:]
            visual_assessment = processor.batch_decode(vision_tokens, skip_special_tokens=True)[
                0
            ].strip()
            if visual_assessment not in {"0", "1", "2", "unknown"}:
                raise ValueError("incomplete visual assessment")
            visual_elapsed_s = time.monotonic() - started
            system_prompt, context_text = job["prompt"].split("\nCONTEXT_DATA_JSON:\n", 1)
            context_data = json.loads(context_text)
            context_data["visual_bottle_count_from_same_vlm"] = visual_assessment
            facts = context_data["current_facts"]
            # This is a veto, never a positive grasp/identity fact. Uncertain or
            # ambiguous visual evidence requires clarification at the pickup site.
            require_clarification = needs_visual_clarification(
                visual_assessment,
                at_source=bool(
                    job["active_mission"] and context_data["request"]["source"] in facts["base_at"]
                ),
                held=facts["verified_held_object"],
                selected=facts["selected_object"],
            )
            context_data["visual_clarification_required"] = require_clarification
            missing_slots = (
                missing_request_slots(context_data["instruction"])
                if not job["active_mission"]
                else ()
            )
            context_data["missing_request_slots"] = missing_slots
            content.append({"type": "text", "text": json.dumps(context_data, ensure_ascii=False)})
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ]
            inputs = processor(
                text=[
                    processor.apply_chat_template(
                        messages, add_generation_prompt=True, tokenize=False
                    )
                ],
                images=images,
                return_tensors="pt",
            ).to(device=config.device, dtype=getattr(torch, config.dtype))
            pixels = inputs["pixel_values"]
            if not pixels.numel() or not torch.isfinite(pixels).all():
                raise ValueError("missing or invalid pixel tensor")
            tensor_digest = hashlib.sha256(
                pixels.detach().float().cpu().numpy().tobytes()
            ).hexdigest()
            input_length = inputs["input_ids"].shape[1]
            grammar = build_transformers_prefix_allowed_tokens_fn(
                tokenizer_data,
                decision_parser(
                    job["active_mission"],
                    [] if require_clarification else job["action_options"],
                    request_allowed=not missing_slots,
                ),
            )
            with torch.inference_mode():
                output = model.generate(
                    **inputs,
                    max_new_tokens=config.max_new_tokens,
                    do_sample=False,
                    prefix_allowed_tokens_fn=grammar,
                )
            generated = output[:, input_length:]
            # resource is Unix-only; this backend targets the thesis Linux workstation.
            reply = BackendReply(
                raw=processor.batch_decode(generated, skip_special_tokens=True)[0].strip(),
                receipts=tuple(PixelReceipt.model_validate(r) for r in receipts),
                tensor_sha256=tensor_digest,
                tensor_shape=tuple(pixels.shape),
                elapsed_s=time.monotonic() - started,
                peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                generated_tokens=int(generated.shape[1] + vision_tokens.shape[1]),
                visual_assessment=visual_assessment,
                visual_elapsed_s=visual_elapsed_s,
                visual_clarification_required=require_clarification,
            )
            connection.send({"reply": reply.model_dump()})
    except (Exception, KeyboardInterrupt) as exc:
        # Process boundary: every model/library failure is surfaced to the owner.
        connection.send({"error": f"{type(exc).__name__}: {exc}"})
    finally:
        connection.close()


class LocalVLM:
    def __init__(self, config: PlannerConfig, model_path: Path) -> None:
        self.config = config
        self.model_path = model_path
        self._process: BaseProcess | None = None
        self._connection: Connection | None = None
        self._deadline: float | None = None

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("backend already started")
        if not (self.model_path / "config.json").is_file():
            raise ValueError("local model directory required; runtime never downloads weights")
        context = mp.get_context("spawn")
        parent, child = context.Pipe()
        self._connection = parent
        self._process = context.Process(
            target=model_worker,
            args=(child, self.config, str(self.model_path)),
            daemon=True,
        )
        self._process.start()
        child.close()
        try:
            if not parent.poll(self.config.startup_timeout_s):
                raise TimeoutError("VLM model loading timed out")
            ready = parent.recv()
            if not ready.get("ready"):
                raise RuntimeError(ready.get("error", "VLM startup failed"))
        except BaseException:
            self.close()
            raise

    def submit(
        self,
        prompt: str,
        images: list[dict[str, Any]],
        *,
        active_mission: bool = True,
        action_options: list[dict[str, Any]] | None = None,
    ) -> None:
        if self._connection is None or self._process is None or not self._process.is_alive():
            raise RuntimeError("VLM backend is unavailable; restart explicitly")
        if self._deadline is not None:
            raise RuntimeError("one inference at a time")
        if not 1 <= len(images) <= 2:
            raise ValueError("one or two actual images required")
        self._deadline = time.monotonic() + self.config.timeout_s
        self._connection.send(
            {
                "prompt": prompt,
                "images": images,
                "active_mission": active_mission,
                "action_options": action_options or [],
            }
        )

    def poll(self) -> BackendReply | None:
        if self._deadline is None or self._connection is None:
            return None
        # Check deadline BEFORE reading: buffered late answers cannot be admitted.
        if time.monotonic() >= self._deadline:
            self.close()
            raise TimeoutError("VLM inference exceeded deadline; process terminated")
        if self._connection.poll():
            try:
                message = self._connection.recv()
            except EOFError as exc:
                self.close()
                raise RuntimeError("VLM worker disconnected") from exc
            self._deadline = None
            if "error" in message:
                self.close()
                raise RuntimeError(message["error"])
            return BackendReply.model_validate(message["reply"])
        if self._process is not None and not self._process.is_alive():
            self.close()
            raise RuntimeError("VLM worker exited")
        return None

    def close(self) -> None:
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=2)
            self._process.close()
            self._process = None
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._deadline = None
