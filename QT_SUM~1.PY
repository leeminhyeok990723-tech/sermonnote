# 큐티인 매일 큐티 자동 요약 → summaries.json
# 매일 새벽 GitHub Actions가 실행: 최신 영상 자막 받아 Gemini로 요약해 저장.
import os, json, re, html, urllib.request
from yt_dlp import YoutubeDL

PLAYLIST = "https://www.youtube.com/playlist?list=PLvn_5y4iSsmxh7NVg8yhk9eqdyPGkm6fg"
GKEY = os.environ.get("GEMINI_API_KEY", "").strip()
OUT = "summaries.json"
MODELS = ["gemini-flash-latest","gemini-2.5-flash","gemini-2.0-flash","gemini-2.5-flash-lite","gemini-1.5-flash-latest"]

SYS = ("너는 '큐티인'(매일 큐티) 영상 자막을 신자의 큐티 노트로 정리한다. "
  "진행 인사, 광고, 홈페이지/전화 문의 안내는 제외한다. "
  "설교자가 나눈 대지(보통 1~3개)를 그대로 살려, 각 대지는 "
  "text(대지 제목/핵심 한 줄), summary(그 대지 내용을 여러 개의 상세한 불릿으로 충분히 정리한 배열), "
  "apps(적용질문 배열)로 구성한다. intro에는 본문 배경/도입 요약을 넣는다. "
  "성경 인용은 약칭 없이 풀어서(예: 신명기). "
  '반드시 이 JSON만 출력: {"title":"","ref":"","intro":"","points":[{"text":"","summary":[""],"apps":[""]}]}')

def newest_video():
    with YoutubeDL({"extract_flat":"in_playlist","playlistend":1,"quiet":True,"skip_download":True}) as y:
        info = y.extract_info(PLAYLIST, download=False)
    e = info["entries"][0]
    return e["id"], e.get("title","")

def get_transcript(vid):
    url = "https://www.youtube.com/watch?v=" + vid
    with YoutubeDL({"skip_download":True,"quiet":True,"writesubtitles":True,
                    "writeautomaticsub":True,"subtitleslangs":["ko","ko-KR"]}) as y:
        info = y.extract_info(url, download=False)
    tracks = None
    for key in ("subtitles","automatic_captions"):
        d = info.get(key) or {}
        for k in d:
            if k.startswith("ko"):
                tracks = d[k]; break
        if tracks: break
    if not tracks: return ""
    order = {"json3":0,"srv3":1,"srv1":2,"vtt":3}
    tracks = sorted(tracks, key=lambda t: order.get(t.get("ext"), 9))
    turl = tracks[0]["url"]; ext = tracks[0].get("ext")
    data = urllib.request.urlopen(turl, timeout=40).read().decode("utf-8","ignore")
    if ext == "json3":
        j = json.loads(data); parts = []
        for ev in j.get("events", []):
            for s in ev.get("segs", []) or []:
                parts.append(s.get("utf8",""))
        text = "".join(parts)
    elif ext == "vtt":
        out = []
        for ln in data.splitlines():
            t = ln.strip()
            if not t or "-->" in t or t.isdigit() or t.startswith("WEBVTT"): continue
            out.append(t)
        text = " ".join(out)
    else:
        text = html.unescape(re.sub(r"<[^>]+>", " ", data))
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_title(title):
    parts = [p.strip() for p in re.split(r"[｜|]", title) if p.strip()]
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", title)
    date = "%04d-%02d-%02d" % (int(m.group(1)),int(m.group(2)),int(m.group(3))) if m else ""
    refpat = re.compile(r"\d+\s*[:：]\s*\d+")
    ref = ""; subj = ""
    for p in parts:
        if re.search(r"\d{4}-\d", p): continue
        if "목사" in p or "큐티노트" in p or "큐티인" in p: continue
        if refpat.search(p):
            if not ref: ref = p
        elif not subj:
            subj = p
    return date, subj, ref

def summarize(transcript, subj, ref):
    body = {"system_instruction":{"parts":[{"text":SYS}]},
      "contents":[{"role":"user","parts":[{"text":"[제목] %s / 본문 %s\n\n[자막]\n%s" % (subj, ref, transcript)}]}],
      "generationConfig":{"temperature":0.4,"responseMimeType":"application/json"}}
    data = json.dumps(body).encode()
    last = ""
    for m in MODELS:
        try:
            req = urllib.request.Request(
              "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % m,
              data=data, headers={"content-type":"application/json","x-goog-api-key":GKEY})
            r = urllib.request.urlopen(req, timeout=180).read().decode()
            txt = json.loads(r)["candidates"][0]["content"]["parts"][0]["text"]
            s = txt.find("{"); e = txt.rfind("}")
            return json.loads(txt[s:e+1])
        except Exception as ex:
            last = str(ex); continue
    raise SystemExit("Gemini 실패: " + last)

def main():
    if not GKEY: raise SystemExit("GEMINI_API_KEY 가 없어요 (GitHub Secret 확인)")
    vid, title = newest_video()
    date, subj, ref = parse_title(title)
    print("최신:", date, "|", subj, "|", ref, "|", vid)
    try:
        db = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        db = {"sermons": []}
    if not isinstance(db, dict) or "sermons" not in db:
        db = {"sermons": []}
    key = date or vid
    if any(s.get("id") == key for s in db["sermons"]):
        print("이미 있음:", key); return
    tr = get_transcript(vid)
    if len(tr) < 200:
        raise SystemExit("자막을 못 받았어요 (길이 %d)" % len(tr))
    obj = summarize(tr, subj, ref)
    entry = {
      "id": key, "date": date,
      "title": obj.get("title") or subj,
      "ref": obj.get("ref") or ref,
      "category": "큐티인", "detail": "", "preacher": "김양재 목사", "scripture": "",
      "intro": obj.get("intro",""),
      "points": [{"text": p.get("text",""),
                  "summary": p.get("summary", p.get("sum", [])),
                  "apps": p.get("apps", [])} for p in (obj.get("points") or [])],
    }
    db["sermons"].insert(0, entry)
    db["sermons"] = db["sermons"][:120]
    json.dump(db, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print("추가됨:", key)

if __name__ == "__main__":
    main()
