import qrcode
import sys
import os
from urllib.parse import urlparse


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except ValueError:
        return False


def generate_qr(url: str, output_file: str = "qrcode.png") -> None:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if not is_valid_url(url):
        print(f"[EROARE] URL invalid: '{url}'")
        sys.exit(1)

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_file)

    print(f"[OK] Cod QR generat pentru: {url}")
    print(f"[OK] Salvat ca:             {os.path.abspath(output_file)}")
    print("     Scanează imaginea pentru a fi redirecționat automat spre site.")


if __name__ == "__main__":
    link = "http://172.20.10.4:8080/pay/1"
    output = "parkside_qr.png"

    generate_qr(link, output)
