"""Guide voiceover for the product film with Amazon Polly (neural Kajal, en-IN) from docs/video/product_vo.txt.
Writes video/public/audio/vo_product/k{n}.mp3. Drop your own reads in with the same names and re-run
product_timeline.py: the film re-times itself."""
import re
from pathlib import Path
import boto3

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video/public/audio/vo_product"
OUT.mkdir(parents=True, exist_ok=True)
blocks = re.findall(r"BLOCK (\d+).*?\n(.+?)(?:\n\n|\Z)", (ROOT / "docs/video/product_vo.txt").read_text(encoding="utf-8"), re.S)
polly = boto3.client("polly", region_name="ap-south-1")
for n, text in blocks:
    ssml = f'<speak><prosody rate="102%">{text.strip()}</prosody></speak>'
    r = polly.synthesize_speech(Text=ssml, TextType="ssml", OutputFormat="mp3", SampleRate="24000", VoiceId="Kajal", Engine="neural")
    (OUT / f"k{n}.mp3").write_bytes(r["AudioStream"].read())
    print("k" + n)
