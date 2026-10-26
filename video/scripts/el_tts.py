"""ElevenLabs read of narration blocks from docs/video/product_vo.txt -> public/audio/VO_ELEVENLABS/K{n}.mp3.

Same voice and settings as the website takes (Kashvi, eleven_multilingual_v2), so new blocks match the old.
Key: ELEVENLABS_API_KEY from the environment or the repo's .env. Then run el_import.py and product_timeline.py.
    .venv\\Scripts\\python video/scripts/el_tts.py 13 14
"""
import os, re, sys
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video/public/audio/VO_ELEVENLABS"
VOICE = "t65y7fZZv3UrpG7b4PUD"     # Kashvi
SETTINGS = {"stability": 0.45, "similarity_boost": 0.75, "style": 0.15, "use_speaker_boost": True, "speed": 1.0}
# spoken spellings only; the written script stays as is
SAY = {"WaterGuard": "Water Guard", "OpenCV 5": "Open C V five", "ECC": "E C C", "MAGSAC": "mag-sack", "EC2": "E C 2", "Super VL": "Super V L",
       "AWS": "A W S"}

if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    key = os.environ["ELEVENLABS_API_KEY"]
    blocks = dict(re.findall(r"BLOCK (\d+).*?\n(.+?)(?:\n\n|\Z)", (ROOT / "docs/video/product_vo.txt").read_text(encoding="utf-8"), re.S))
    OUT.mkdir(parents=True, exist_ok=True)
    for n in sys.argv[1:]:
        text = blocks[n].strip()
        for a, b in SAY.items():
            text = text.replace(a, b)
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
                          headers={"xi-api-key": key}, timeout=120,
                          json={"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": SETTINGS})
        r.raise_for_status()
        (OUT / f"K{n}.mp3").write_bytes(r.content)
        print(f"K{n}.mp3", len(r.content), "bytes")
