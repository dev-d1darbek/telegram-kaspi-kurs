"""Kaspi фискалдық чек тексеру."""

import io
import re
import json
import cv2
import httpx
import numpy as np
from typing import Optional
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams
import pymupdf as fitz


QR_LINK_RE = re.compile(r"https://receipt\.kaspi\.kz/web/fiscal\?[^\s\"'<>]+")
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


# === PDF TEXT ===
def pdf_text(pdf_bytes: bytes) -> str:
    parts = []
    try:
        t = extract_text(io.BytesIO(pdf_bytes), laparams=LAParams()) or ""
        if t.strip():
            parts.append(t)
    except Exception:
        pass
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pts = [p.get_text("text") for p in doc if p.get_text("text").strip()]
        if pts:
            parts.append("\n".join(pts))
    except Exception:
        pass
    return "\n\n".join(parts)


# === QR ===
def pdf_qr(pdf_bytes: bytes) -> Optional[str]:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None
    det = cv2.QRCodeDetector()
    for page in doc:
        # суреттерден
        for info in page.get_images(full=True):
            try:
                pix = fitz.Pixmap(doc, info[0])
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, pix.n
                )
                if pix.n == 1:
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                elif pix.n == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                data, _, _ = det.detectAndDecode(img)
                if data and "kaspi" in data.lower():
                    return data.strip()
            except Exception:
                continue
        # растрдан
        try:
            pix = page.get_pixmap(dpi=300)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 1:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            data, _, _ = det.detectAndDecode(img)
            if data and "kaspi" in data.lower():
                return data.strip()
        except Exception:
            continue
    return None


# === NUXT RESOLVER ===
def _resolve_nuxt(data: list, ref, depth: int = 0, inside: bool = False):
    """Nuxt devalue: inside=True → сан=сілтеме, top-level → сан=литерал."""
    if depth > 40:
        return None
    if inside and isinstance(ref, int) and not isinstance(ref, bool):
        return _resolve_nuxt(data, data[ref], depth + 1, False) if 0 <= ref < len(data) else None
    if isinstance(ref, dict):
        return {k: _resolve_nuxt(data, v, depth + 1, True) for k, v in ref.items()}
    if isinstance(ref, list):
        return [_resolve_nuxt(data, v, depth + 1, True) for v in ref]
    return ref


# === KASPI FETCH ===
def kaspi_fetch(url: str) -> dict:
    with httpx.Client(timeout=20, follow_redirects=True, headers=HTTP_HEADERS) as c:
        r = c.get(url)
        r.raise_for_status()
        html = r.text
    m = re.search(
        r'<script type="application/json" id="__NUXT_DATA__"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        raise ValueError("Kaspi беті өзгерген (__NUXT_DATA__ жоқ)")
    data = json.loads(m.group(1))
    idx = next(
        (i for i, it in enumerate(data)
         if isinstance(it, dict) and "amount" in it and "extTranId" in it),
        None,
    )
    if idx is None:
        raise ValueError("Чек объектісі табылмады")
    r = _resolve_nuxt(data, data[idx], inside=False) or {}
    params = {}
    for p in r.get("payParameters") or []:
        if isinstance(p, dict) and "name" in p and "value" in p:
            params[str(p["name"])] = p["value"]
    return {
        "amount": r.get("amount"),
        "receipt_no": r.get("extTranId"),
        "receipt_link": r.get("receiptLink"),
        "params": params,
    }


# === VERIFY ===
def verify(pdf_bytes: bytes, expected_amount: int, expected_bin: str) -> dict:
    """
    Толық тексеру.
    Returns: {"valid": bool, "error": str|None, "kaspi": dict, "checks": [...]}
    """
    text = pdf_text(pdf_bytes)
    qr_url = None
    m = QR_LINK_RE.search(text)
    if m:
        qr_url = m.group(0)
    if not qr_url:
        qr_url = pdf_qr(pdf_bytes)
    if not qr_url:
        return {"valid": False, "error": "QR-код немесе Kaspi сілтемесі табылмады",
                "kaspi": None, "checks": []}

    try:
        kaspi = kaspi_fetch(qr_url)
    except Exception as e:
        return {"valid": False, "error": f"Kaspi деректері алынбады: {e}",
                "kaspi": None, "checks": []}

    params = kaspi.get("params") or {}
    checks = []

    # 1. Сома
    k_amt = kaspi.get("amount")
    if k_amt is None:
        return {"valid": False, "error": "Kaspi-де сома жоқ",
                "kaspi": kaspi, "checks": []}
    checks.append({
        "name": "Сома",
        "ok": int(k_amt) == int(expected_amount),
        "pdf": expected_amount,
        "kaspi": int(k_amt),
    })

    # 2. ЖСН/БСН
    k_bin = str(params.get("ИИН/БИН продавца", "")).strip()
    exp_bin = str(expected_bin or "").strip()
    if exp_bin:
        checks.append({
            "name": "Сатушы ЖСН/БСН",
            "ok": k_bin == exp_bin,
            "pdf": exp_bin,
            "kaspi": k_bin,
        })

    # 3. Чек нөмірі PDF-те бар ма
    rno = kaspi.get("receipt_no")
    if rno and text:
        checks.append({
            "name": "Чек № PDF-те",
            "ok": rno in text,
            "pdf": "✓" if rno in text else "—",
            "kaspi": rno,
        })

    # 4. РНМ / ФП / ЗНМ PDF-те бар ма
    for pname in ["РНМ", "ФП", "ЗНМ"]:
        pval = str(params.get(pname, "")).strip()
        if not pval:
            continue
        checks.append({
            "name": f"{pname} PDF-те",
            "ok": pval in text,
            "pdf": "✓" if pval in text else "—",
            "kaspi": pval,
        })

    has_mismatch = any(not c["ok"] for c in checks)
    return {
        "valid": not has_mismatch,
        "error": None,
        "kaspi": kaspi,
        "checks": checks,
    }


# ============================================================
# САТУШЫ ДЕРЕКТЕРІН ЧЕКТЕН АЛУ
# ============================================================
def extract_seller_info(pdf_bytes: bytes) -> dict:
    """PDF/Kaspi чегінен сатушының атауы мен ЖСН/БСН-ды алуға тырысады.

    Бұл функция тек деректерді шығарады; төлемнің түпнұсқалығын дәлелдемейді.
    Returns: {"company": str|None, "company_bin": str|None}
    """
    text = pdf_text(pdf_bytes)
    company = None
    company_bin = None

    # ИП атауы: "ИП ХАДИША", жолдың соңы немесе келесі белгілі өріс.
    patterns = [
        r"(?im)\bИП\s+([^\r\n]{2,80})",
        r"(?im)\bИП\s*[:：]\s*([^\r\n]{2,80})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            candidate = re.split(r"\s{2,}|Сату|Түбіртек|Чек", m.group(1), maxsplit=1)[0]
            candidate = candidate.strip(" .,:;—-")
            if candidate and len(candidate) <= 80:
                company = candidate
                break

    # Kaspi чегіндегі сатушының ЖСН/БСН-ы.
    m = re.search(
        r"(?i)(?:ИИН\s*/\s*БИН|ЖСН\s*/?\s*БСН|БИН|ЖСН|ИИН)[^0-9]{0,30}(\d{12})",
        text,
    )
    if m:
        company_bin = m.group(1)

    # Егер PDF мәтінінде табылмаса, QR сілтемесінен Kaspi бетін қараймыз.
    qr_url = None
    m = QR_LINK_RE.search(text)
    if m:
        qr_url = m.group(0)
    if not qr_url:
        qr_url = pdf_qr(pdf_bytes)

    if qr_url and (not company or not company_bin):
        try:
            kaspi = kaspi_fetch(qr_url)
            params = kaspi.get("params") or {}
            if not company_bin:
                company_bin = str(
                    params.get("ИИН/БИН продавца")
                    or params.get("ИИН/БИН продавца:")
                    or ""
                ).strip() or None
            if not company:
                for label in ("Наименование продавца", "Продавец", "ИП"):
                    value = params.get(label)
                    if value:
                        company = str(value).strip()
                        break
        except Exception:
            # QR бар, бірақ Kaspi беті қолжетімсіз болуы мүмкін.
            pass

    if company_bin and not re.fullmatch(r"\d{12}", company_bin):
        company_bin = None
    return {"company": company, "company_bin": company_bin}
