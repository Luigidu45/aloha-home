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

"""CompressedImage to Image, for robots whose driver only publishes compressed
frames. ``CameraMuxModule`` takes raw ``Image`` inputs."""

from __future__ import annotations

from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.stream import In, Out
from dimos.msgs.sensor_msgs.CompressedImage import CompressedImage
from dimos.msgs.sensor_msgs.Image import Image
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class ImageDecodeModule(Module):
    """Republish a CompressedImage stream as decoded frames."""

    compressed_in: In[CompressedImage]
    image_out: Out[Image]

    @rpc
    def start(self) -> None:
        super().start()
        self.register_disposable(Disposable(self.compressed_in.subscribe(self._decode)))

    def _decode(self, msg: CompressedImage) -> None:
        try:
            self.image_out.publish(msg.decode())
        except Exception:
            logger.warning("dropping undecodable %s frame", msg.format, exc_info=True)
