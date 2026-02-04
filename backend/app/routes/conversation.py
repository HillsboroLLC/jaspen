from __future__ import annotations
import json, os, re, time, uuid
from pathlib import Path
from typing import Dict, List, Tuple
from flask import Blueprint, request, jsonify, current_app

# fail-open import so we never 500 if lib/env missing
try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None

conversation_bp = Blueprint("conversation", __name__)

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
ROOT = Path(__file__).resolve().parents[2]
SESS_DIR = Path(os.getenv("SESSION_DIR", ROOT / "runtime" / "sessions"))
SESS_DIR.mkdir(parents=True, exist_ok=True)

SLOTS = ("target","problem","solution","budget","timeline","channel","risks","kpi","constraints")
WEIGHTS = {"target":2.0,"problem":2.0,"solution":1.8,"budget":1.2,"timeline":1.2,"channel":1.0,"risks":1.0,"kpi":0.8,"constraints":0.6}
CLIENT = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")) if (Anthropic and os.getenv("ANTHROPIC_API_KEY")) else None

def _norm(s: str) -> str: return " ".join((s or "").lower().split())
def _p(sid:str) -> Path: return SESS_DIR / f"{sid}.json"
def _load(sid:str)->Dict:
    p=_p(sid)
    if p.exists():
        try: return json.loads(p.read_text())
        except Exception: return {}
    return {}
def _save(sid:str,data:Dict)->None:
    tmp=_p(f"{sid}.{int(time.time()*1000)}.tmp"); tmp.write_text(json.dumps(data,ensure_ascii=False)); tmp.rename(_p(sid))

def _strip_lists(t:str)->str:
    if not t: return ""
    lines=[ln for ln in t.splitlines() if not re.match(r"^\s*([•\-*]|\d+\.)\s",ln)]
    return re.sub(r"\s+"," "," ".join(ln.strip() for ln in lines if ln.strip())).strip()

def _ensure_one_q(text:str, fallback_q:str)->str:
    txt=_strip_lists(text)
    parts=re.split(r"(?<=[.!?])\s+",txt)
    if len(parts)>2: txt=" ".join(parts[:2])
    if "?" not in txt: txt=(txt+" "+fallback_q.rstrip("?")+"?").strip() if txt else fallback_q.rstrip("?")+"?"
    if len(txt)>480: txt=txt[:470].rstrip()+"?"
    return txt

def _dedupe(history:List[Dict[str,str]], reply:str)->str:
    last_ai=next((m for m in reversed(history) if m.get("role")=="assistant"),None)
    return (reply.rstrip("?")+" — quick clarification?") if (last_ai and _norm(last_ai.get("content",""))==_norm(reply)) else reply
def _extract_slots(text:str)->Dict[str,str]:
    t=" "+_norm(text)+" "
    out={k:None for k in SLOTS}
    m=re.search(r"(smb|mid[- ]market|enterprise|consumer|buyer|it|ops|finance|marketing|sales|developers?)",t);  out["target"]=m.group(0) if m else None
    m=re.search(r"(pain|problem|churn|latency|downtime|compliance|overrun|support|ticket|inefficien|bottleneck)",t); out["problem"]=m.group(0) if m else None
    m=re.search(r"(saas|platform|tool|api|service|app|analytics|agent|automation|market iq)",t);                    out["solution"]=m.group(0) if m else None
    m=re.search(r"(q[1-4]\s*\d{4}|\b(end|late|early)\s+q[1-4]\b|\b\d+\s*(weeks?|months?|quarters?|years?)\b|\b(in|within)\s+a\s+year\b|\bby\s+\w+\s+\d{4}\b|\bnext\s+year\b|\bthis\s+time\s+next\s+year\b|\byear[-\s]*end\b|\bend\s+of\s+year\b|\beoy\b|\beoq[1-4]\b|\bend\s+of\s+q[1-4]\b|\blater\s+this\s+year\b|\bearly\s+next\s+year\b|\bmid\s+next\s+year\b)", t)
    m=re.search(r"(q[1-4]\s*\d{4}|\b\d+\s*(weeks?|months?|quarters?|years?)\b|\bby\s+\w+\s+\d{4}\b)",t);             out["timeline"]=m.group(0) if m else None
    m=re.search(r"(seo|sem|ads?|sales|partners?|resellers?|marketplace|email|social|events?)",t);                    out["channel"]=m.group(0) if m else None
    m=re.search(r"(risk|dependency|constraint|capex|regulatory|privacy|gdpr|security)",t);                           out["risks"]=m.group(0) if m else None
    m=re.search(r"(roi|payback|ltv|cac|mrr|arr|ebitda|retention|conversion|nps)",t);                                  out["kpi"]=m.group(0) if m else None
    m=re.search(r"(hiring|data access|integration|budget ceiling|timeline limit|compliance gate)",t);                out["constraints"]=m.group(0) if m else None
    return out

def _readiness(slots:Dict[str,str])->int:
    score=max_score=0.0
    max_score=sum(WEIGHTS.values())
    for k,w in WEIGHTS.items(): score+=w*(1.0 if slots.get(k) else 0.0)
    return max(0,min(100,round(100*(score/max_score))))

def _next_q(slots:Dict[str,str])->Tuple[str,str]:
    missing=[k for k in SLOTS if not slots.get(k)]
    if not missing: return ("risks","What’s the most material risk to the plan and how would you mitigate it?")
    top=sorted(missing,key=lambda k:WEIGHTS[k],reverse=True)[0]
    qmap={
        "target":"Who exactly is the buyer (role/company size/industry) and what job are they hiring you to do?",
        "problem":"What painful, measurable problem do they have today and how do they handle it now?",
        "solution":"Briefly, what’s the solution’s core mechanism of value versus the status quo?",
        "budget":"What total budget (order of magnitude) can you commit over the next 6–12 months?",
        "timeline":"What’s the target go-live date or time window you’re driving toward?",
        "channel":"Which acquisition channel will likely yield the first scalable traction?",
        "risks":"What’s the most material risk to the plan and how would you mitigate it?",
        "kpi":"What single KPI will define success at the end of this phase?",
        "constraints":"What hard constraints (team, data access, compliance) could block progress?",
    }
    return (top,qmap[top])

SYSTEM_HEAD=(
 "You are a top 0.1% market analyst. Be surgical and assumption-aware. "
 "Provide at most two crisp sentences tailored to the user's latest input, "
 "then ask exactly one high-leverage follow-up. No lists or outlines."
)

def _ask(system_ctx:str, history:List[Dict[str,str]])->str:
    if not CLIENT: return ""
    try:
        resp=CLIENT.messages.create(
            model=ANTHROPIC_MODEL,
            system=f"{SYSTEM_HEAD}\nAnalyst Context: {system_ctx}",
            temperature=0.2,
            max_tokens=350,
            messages=[{"role":m["role"],"content":m["content"]} for m in history if m.get("content")],
        )
        parts = []
        for blk in resp.content:
            if getattr(blk, "type", None) == "text":
                parts.append(blk.text)
        return ("".join(parts)).strip()

    except Exception as e:
        current_app.logger.exception("anthropic_error: %s", e)
        return ""
@conversation_bp.route("/start", methods=["POST"])
def start():
    p=request.get_json(silent=True) or {}
    desc=(p.get("description") or "").strip() or "Let's begin."
    sid=f"conv_{uuid.uuid4().hex[:12]}"
    history=[{"role":"user","content":desc}]
    slots=_extract_slots(desc)
    ctx=f"Known: "+", ".join(f"{k}={v}" for k,v in slots.items() if v) or "—"
    missing=", ".join(k for k in SLOTS if not slots.get(k)) or "—"
    ctx=f"{ctx}. Missing: {missing}."
    _,fallback=_next_q(slots)
    raw=_ask(ctx,history) or "Understood."
    reply=_ensure_one_q(raw,fallback)
    reply=_dedupe(history,reply)
    sess={"session_id":sid,"history":[*history,{"role":"assistant","content":reply}],"slots":slots,"created_at":int(time.time())}
    _save(sid,sess)
    return jsonify({"session_id":sid,"message":reply,"readiness_score":_readiness(slots),"status":"gathering_info"})

@conversation_bp.route("/continue", methods=["POST"])
def cont():
    p=request.get_json(silent=True) or {}
    sid=p.get("session_id") or f"conv_{uuid.uuid4().hex[:12]}"
    user=(p.get("message") or p.get("user_message") or "").strip()
    client_hist=p.get("conversation_history") or []
    sess=_load(sid)
    history=client_hist if client_hist else sess.get("history",[])
    if user:
        if not history or history[-1].get("role")!="user" or _norm(history[-1].get("content",""))!=_norm(user):
            history.append({"role":"user","content":user})
    user_text=" ".join(m["content"] for m in history if m.get("role")=="user")
    slots=_extract_slots(user_text)
    ctx="Known: "+(", ".join(f"{k}={v}" for k,v in slots.items() if v) or "—")
    missing=", ".join(k for k in SLOTS if not slots.get(k)) or "—"
    ctx=f"{ctx}. Missing: {missing}."
    _,fallback=_next_q(slots)
    raw=_ask(ctx,history) or "Got it."
    reply=_ensure_one_q(raw,fallback)
    reply=_dedupe(history,reply)
    new_hist=[*history,{"role":"assistant","content":reply}]
    _save(sid,{"session_id":sid,"history":new_hist,"slots":slots,"updated_at":int(time.time())})
    return jsonify({"session_id":sid,"message":reply,"readiness_score":_readiness(slots),"status":"gathering_info"})
