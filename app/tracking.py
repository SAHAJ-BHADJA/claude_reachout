"""Invisible 1x1 open-tracking pixel (always on)."""
import uuid
from .config import cfg

PIXEL_GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000"
    "010001000002024401003b"
)


def new_id() -> str:
    return uuid.uuid4().hex


def pixel_url(tracking_id: str) -> str:
    return f"{cfg.TRACKING_BASE_URL}/t/o/{tracking_id}.gif"


def inject_pixel(html: str, tracking_id: str) -> str:
    img = (f"<img src=\"{pixel_url(tracking_id)}\" width=\"1\" height=\"1\" alt=\"\" "
           f"style=\"display:block;border:0;width:1px;height:1px\">")
    return html.replace("</div>", img + "</div>", 1) if "</div>" in html else html + img
