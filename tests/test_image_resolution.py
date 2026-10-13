"""Real image bytes exercise the resolution gate without network or model calls."""

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nodes import image_analyst


def picture(size):
    output = io.BytesIO()
    Image.new("RGB", size, "white").save(output, format="PNG")
    return output.getvalue()


class ImageResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, data):
        response = httpx.Response(200, content=data,
                                  headers={"content-type": "image/png"})
        client = AsyncMock()
        client.get.return_value = response
        client.__aenter__.return_value = client
        with patch.object(image_analyst.httpx, "AsyncClient", return_value=client):
            return await image_analyst._fetch_image("https://example.com/picture.png")

    async def test_deepseek_thumbnail_never_reaches_model(self):
        client = AsyncMock()
        client.get.return_value = httpx.Response(
            200, content=picture((480, 360)), headers={"content-type": "image/png"})
        client.__aenter__.return_value = client
        with patch.object(image_analyst.httpx, "AsyncClient", return_value=client), \
                patch.object(image_analyst, "_judge", new_callable=AsyncMock,
                             return_value={"images": [], "best": 0}) as judge, \
                patch.object(image_analyst.db, "bump_counter"):
            choice = await image_analyst.choose("DeepSeek OCR", ["https://example.com/ocr.png"])
        self.assertEqual(choice.url, "")
        self.assertFalse(choice.failed)
        judge.assert_not_awaited()

    async def test_short_edge_cannot_be_compensated_by_long_edge(self):
        self.assertTrue(await self.fetch(picture((1600, 399))) is None)

    async def test_long_edge_must_also_meet_threshold(self):
        self.assertTrue(await self.fetch(picture((799, 799))) is None)

    async def test_threshold_and_orientation(self):
        for size in ((800, 400), (400, 800), (1024, 1024), (1200, 630)):
            with self.subTest(size=size):
                data = picture(size)
                self.assertEqual(await self.fetch(data), data)

    async def test_unreadable_image_is_rejected(self):
        self.assertIsNone(await self.fetch(b"not an image"))

    async def test_truncated_jpeg_with_valid_dimensions_is_rejected(self):
        output = io.BytesIO()
        Image.new("RGB", (800, 400), "white").save(output, format="JPEG")
        self.assertTrue(await self.fetch(output.getvalue()[:-100]) is None)


if __name__ == "__main__":
    unittest.main()
