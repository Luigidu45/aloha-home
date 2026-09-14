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

"""Local model wiring: DimOS YOLO for candidates and CLIP for spatial retrieval."""

import numpy as np
from numpy.typing import NDArray

from dimos.models.embedding.clip import CLIPModel
from dimos.msgs.sensor_msgs.Image import Image


class ClipEmbeddingAdapter:
    """Reuse DimOS's current CLIP model, without legacy random-vector fallbacks."""

    def __init__(self, model: CLIPModel) -> None:
        self.model = model

    def image_vector(self, image: Image) -> NDArray[np.float32]:
        return np.asarray(self.model.embed(image).to_numpy(), dtype=np.float32)

    def get_text_embedding(self, text: str) -> NDArray[np.float32]:
        return np.asarray(self.model.embed_text(text).to_numpy(), dtype=np.float32)
