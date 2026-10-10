"""Guide voiceover with Amazon Polly (neural, Kajal en-IN) from docs/video/vo_blocks.txt.
Writes video/public/audio/vo/k{n}.mp3. Replace these with your own recorded / ElevenLabs reads
(same file names) and re-run make_timeline.py: the whole film re-times itself."""
import re
from pathlib import Path
import boto3

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video/public/audio/vo"
OUT.mkdir(parents=True, exist_ok=True)
blocks = re.findall(r"BLOCK (\d+).*?\n(.+?)(?:\n\n|\Z)", (ROOT / "docs/video/vo_blocks.txt").read_text(encoding="utf-8"), re.S)
polly = boto3.client("polly", region_name="ap-south-1")
for n, text in blocks:
    ssml = f'<speak><prosody rate="104%">{text.strip()}</prosody></speak>'
    r = polly.synthesize_speech(Text=ssml, TextType="ssml", OutputFormat="mp3", SampleRate="24000", VoiceId="Kajal", Engine="neural")
    (OUT / f"k{n}.mp3").write_bytes(r["AudioStream"].read())
    print("k" + n)
