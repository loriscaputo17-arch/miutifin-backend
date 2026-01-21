from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from PIL import Image, ImageDraw, ImageFont
import qrcode
import io
import textwrap
import re
from typing import Optional

router = APIRouter()

class FlyerReq(BaseModel):
    title: str
    page_url: str
    city: Optional[str] = None
    venue: Optional[str] = None
    date_text: Optional[str] = None
    accent: Optional[str] = "#ff2fdc"

def safe_filename(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9\-_\s]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s[:60] or "flyer"

def load_font(size: int) -> ImageFont.FreeTypeFont:
    # Prova DejaVu (quasi sempre presente). In prod metti un font tuo dentro /assets/fonts
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

@router.post("/events/{event_id}/flyer")
def generate_event_flyer(event_id: str, payload: FlyerReq):
    try:
        W, H = 1080, 1920

        # --- base (sfondo) ---
        img = Image.new("RGB", (W, H), (10, 10, 10))
        draw = ImageDraw.Draw(img)

        # gradient semplice
        for y in range(H):
            v = int(10 + (y / H) * 30)
            draw.line([(0, y), (W, y)], fill=(v, v, v))

        # glow accent
        accent = payload.accent or "#ff2fdc"
        draw.rounded_rectangle((60, 80, W-60, 260), radius=48, outline=accent, width=4)

        # --- testi ---
        title_font = load_font(86)
        meta_font = load_font(44)
        small_font = load_font(34)

        # wrap titolo
        title = payload.title.strip()
        lines = textwrap.wrap(title, width=18)[:3]
        title_y = 320
        for line in lines:
            w = draw.textlength(line, font=title_font)
            draw.text(((W - w) / 2, title_y), line, font=title_font, fill=(255, 255, 255))
            title_y += 98

        # meta: data + luogo
        meta_parts = []
        if payload.date_text:
            meta_parts.append(payload.date_text)
        if payload.venue:
            meta_parts.append(payload.venue)
        if payload.city:
            meta_parts.append(payload.city)

        meta = " • ".join(meta_parts) if meta_parts else "Scopri su Miutifin"
        mw = draw.textlength(meta, font=meta_font)
        draw.text(((W - mw) / 2, title_y + 20), meta, font=meta_font, fill=(220, 220, 220))

        # --- QR ---
        qr = qrcode.QRCode(border=1, box_size=10)
        qr.add_data(payload.page_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        qr_size = 360
        qr_img = qr_img.resize((qr_size, qr_size))
        qr_x, qr_y = 90, H - 520
        img.paste(qr_img, (qr_x, qr_y))

        draw.rounded_rectangle((qr_x-14, qr_y-14, qr_x+qr_size+14, qr_y+qr_size+14),
                               radius=24, outline=(255,255,255), width=2)

        draw.text((qr_x, qr_y - 48), "Scansiona per aprire", font=small_font, fill=(255, 255, 255))

        # footer brand
        brand = "miutifin"
        bw = draw.textlength(brand, font=meta_font)
        draw.text((W - bw - 90, H - 220), brand, font=meta_font, fill=(255, 255, 255))

        # --- output ---
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        filename = f"miutifin-{safe_filename(payload.title)}-{event_id}.png"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

        return StreamingResponse(buf, media_type="image/png", headers=headers)

    except Exception:
        raise HTTPException(status_code=500, detail="Flyer generation error")
