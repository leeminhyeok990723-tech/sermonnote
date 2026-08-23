# 우리들교회 자동 요약 → summaries.json
# 최신 영상: RSS(공개 XML)로 확실히 / 자막: youtube-transcript-api / 요약: Gemini
import os, json, re, urllib.request, datetime
import xml.etree.ElementTree as ET
from youtube_transcript_api import YouTubeTranscriptApi

GKEY = os.environ.get("GEMINI_API_KEY", "").strip()
FORCE = os.environ.get("FORCE", "").strip()
COOKIES = os.environ.get("YT_COOKIES", "")
COOKIEFILE = None
if COOKIES.strip():
    COOKIEFILE = "yt_cookies.txt"
    with open(COOKIEFILE, "w", encoding="utf-8") as _f:
        _f.write(COOKIES)
OUT = "summaries.json"
MODELS = ["gemini-flash-latest","gemini-2.5-flash","gemini-2.0-flash","gemini-2.5-flash-lite","gemini-1.5-flash-latest"]

PL = {
  "큐티인":     "PLvn_5y4iSsmxh7NVg8yhk9eqdyPGkm6fg",
  "주일설교":   "PLC2TbiZou_9zSvGZHOha8CnYS3Y7FRFuX",
  "사역자설교": "PLC2TbiZou_9zzJUv1KPLv3OwRAvix_Wo1",
}

SYS_QT = ("너는 '큐티인'(매일 큐티) 영상 자막을 신자의 큐티 노트로 정리한다. "
  "진행 인사, 광고, 홈페이지/전화 문의 안내는 제외한다. "
  "설교자가 나눈 대지(보통 1~3개)를 그대로 살려, 각 대지는 "
  "text(대지 제목/핵심 한 줄), summary(그 대지 내용을 여러 개의 상세한 불릿으로 충분히 정리한 배열), "
  "apps(적용질문 배열)로 구성한다. intro에는 본문 배경/도입 요약을 넣는다. 성경 인용은 약칭 없이 풀어서(예: 신명기). "
  '반드시 이 JSON만 출력: {"title":"","ref":"","preacher":"","intro":"","points":[{"text":"","summary":[""],"apps":[""]}]}')

SYS_SERMON = ("너는 한국 개신교 예배 설교 자막을 신자의 설교 노트로 정리한다. "
  "예배 인사, 찬양, 광고, 헌금/공지, 개인 신변잡담은 제외하고 설교 본론만 다룬다. "
  "설교자가 나눈 대지(보통 2~4개)를 그대로 살려, 각 대지는 "
  "text(대지 제목/핵심 한 줄), summary(그 대지에서 다룬 내용을 여러 개의 상세하고 긴 불릿으로 충분히 정리한 배열 — 짧게 줄이지 말 것), "
  "apps(삶에 적용할 적용질문 1~3개 배열)로 구성한다. intro에는 설교 도입/본문 배경을 넣는다. 성경 인용은 약칭 없이 풀어서(예: 열왕기하). "
  '반드시 이 JSON만 출력: {"title":"","ref":"","preacher":"","intro":"","points":[{"text":"","summary":[""],"apps":[""]}]}')

def kst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)

def decide_sources():
    f = FORCE
    if f == "큐티인":   return [("큐티인","큐티인")], SYS_QT
    if f == "수요예배": return [("사역자설교","수요예배")], SYS_SERMON
    if f == "주일예배": return [("주일설교","주일예배"),("사역자설교","주일예배")], SYS_SERMON
    n = kst_now(); wd = n.weekday(); h = n.hour
    if wd == 2 and 21 <= h <= 23: return [("사역자설교","수요예배")], SYS_SERMON
    if wd == 6 and 16 <= h <= 18: return [("주일설교","주일예배"),("사역자설교","주일예배")], SYS_SERMON
    return [("큐티인","큐티인")], SYS_QT

def newest_from_rss(plid):
    url = "https://www.youtube.com/feeds/videos.xml?playlist_id=" + plid
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8","ignore")
    ns = {"a":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"}
    root = ET.fromstring(xml); out = []
    for e in root.findall("a:entry", ns):
        v = e.find("yt:videoId", ns); t = e.find("a:title", ns); p = e.find("a:published", ns)
        if v is None or not v.text: continue
        out.append((v.text, (t.text or "") if t is not None else "", (p.text or "") if p is not None else ""))
    return out

def get_transcript(vid):
    langs = ["ko","ko-KR","ko-x-autogen"]
    if COOKIEFILE:
        data = YouTubeTranscriptApi.get_transcript(vid, languages=langs, cookies=COOKIEFILE)
    else:
        data = YouTubeTranscriptApi.get_transcript(vid, languages=langs)
    txt = " ".join((x.get("text","") or "") for x in data)
    txt = re.sub(r"\[[^\]]*\]", " ", txt); txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def parse_title(title):
    title = title or ""
    title = re.sub(r"\[[^\]]*\]", " ", title)
    parts = [p.strip() for p in re.split(r"[｜|/]", title) if p.strip()]
    m = re.search(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", title)
    date = "%04d-%02d-%02d" % (int(m.group(1)),int(m.group(2)),int(m.group(3))) if m else ""
    refpat = re.compile(r"[가-힣]+\s*\d+\s*[:：]\s*\d+")
    prpat = re.compile(r"([가-힣A-Za-z]+\s*목사)")
    ref=""; subj=""; preacher=""
    for p in parts:
        if re.search(r"\d{4}[-.]\d", p): continue
        pm = prpat.search(p)
        if pm and not preacher: preacher = pm.group(1).strip()
        if refpat.search(p):
            if not ref: ref = refpat.search(p).group(0)
        elif "목사" not in p and "큐티" not in p and not subj:
            subj = p
    return date, subj, ref, preacher

def summarize(sys, transcript, subj, ref):
    body = {"system_instruction":{"parts":[{"text":sys}]},
      "contents":[{"role":"user","parts":[{"text":"[제목] %s / 본문 %s\n\n[자막]\n%s" % (subj, ref, transcript)}]}],
      "generationConfig":{"temperature":0.4,"responseMimeType":"application/json"}}
    data = json.dumps(body).encode(); last=""
    for m in MODELS:
        try:
            req = urllib.request.Request(
              "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % m,
              data=data, headers={"content-type":"application/json","x-goog-api-key":GKEY})
            r = urllib.request.urlopen(req, timeout=240).read().decode()
            txt = json.loads(r)["candidates"][0]["content"]["parts"][0]["text"]
            s = txt.find("{"); e = txt.rfind("}")
            return json.loads(txt[s:e+1])
        except Exception as ex:
            last = str(ex); continue
    raise SystemExit("Gemini 실패: " + last)

def load_db():
    try:
        db = json.load(open(OUT, encoding="utf-8"))
        if isinstance(db, dict) and "sermons" in db: return db
    except Exception: pass
    return {"sermons": []}

def recent_ok(pub):
    try:
        d = datetime.datetime.strptime(pub[:10], "%Y-%m-%d")
        return (kst_now() - d).days <= 2
    except Exception:
        return True

def main():
    if not GKEY: raise SystemExit("GEMINI_API_KEY 가 없어요")
    sources, sys = decide_sources()
    db = load_db(); added = 0
    print("KST:", kst_now().strftime("%Y-%m-%d %H:%M (%a)"), "| FORCE:", FORCE or "auto", "| sources:", sources)
    for plname, cat in sources:
        try:
            cands = newest_from_rss(PL[plname])
        except Exception as ex:
            print("RSS 실패:", plname, str(ex)[:100]); continue
        print(plname, "후보:", [(v, t[:20]) for v,t,p in cands[:3]])
        for vid, title, pub in cands:
            if any(s.get("vid")==vid and s.get("category")==cat for s in db["sermons"]):
                print("최신은 이미 있음:", cat, vid); break
            if cat != "큐티인" and not recent_ok(pub):
                print("최근 업로드 아님 → 건너뜀:", cat, pub[:10], title[:30]); break
            try:
                tr = get_transcript(vid)
            except Exception as ex:
                print("자막 실패 → 다음 후보:", vid, str(ex)[:90]); continue
            if len(tr) < 200:
                print("자막 짧음/없음:", vid, len(tr)); continue
            tr = tr[:45000]
            date, subj, ref, preacher = parse_title(title)
            if not date: date = pub[:10] or kst_now().strftime("%Y-%m-%d")
            try:
                obj = summarize(sys, tr, subj, ref)
            except SystemExit as ex:
                print("요약 실패:", str(ex)[:120]); break
            entry = {
              "id": date + "-" + cat, "vid": vid, "date": date,
              "title": obj.get("title") or subj or title[:30],
              "ref": obj.get("ref") or ref, "category": cat, "detail": "",
              "preacher": obj.get("preacher") or preacher or ("김양재 목사" if cat=="큐티인" else ""),
              "scripture": "", "intro": obj.get("intro",""),
              "points": [{"text": p.get("text",""),
                          "summary": p.get("summary", p.get("sum", [])),
                          "apps": p.get("apps", [])} for p in (obj.get("points") or [])],
            }
            db["sermons"].insert(0, entry); added += 1
            print("추가됨:", cat, entry["id"], entry["title"]); break
    db["sermons"] = db["sermons"][:200]
    json.dump(db, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print("총 추가:", added)

if __name__ == "__main__":
    main()
