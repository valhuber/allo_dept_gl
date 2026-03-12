"""
AI Project Identification — Request Pattern
=============================================
Uses `SysProjectReq` as a Request-Pattern table:
  - Request fields:  contractor_id, description
  - Response fields: matched_project_id, confidence, reason, request_text

When a Charge arrives with project_id=None and a description, an early_row_event
calls get_project_from_ai() which inserts a SysProjectReq.  The early event on
SysProjectReq (select_project_via_ai) runs the fuzzy match and writes the response
fields back.  The Charge handler then sets charge.project_id.

Fuzzy match strategy:
  1. If OPENAI_API_KEY is set: ask GPT to rank active projects by name similarity
     and the contractor's historical project activity.
  2. Fallback (no API key): score by simple substring / token overlap with project
     name; break ties by which project the contractor has charged most recently.
"""
import os
import json
import logging
from pathlib import Path
from logic_bank.logic_bank import Rule
from logic_bank.exec_row_logic.logic_row import LogicRow
from database import models

app_logger = logging.getLogger("api_logic_server_app")


# ── AI handler (fires on SysProjectReq insert) ────────────────────────────────

def select_project_via_ai(row: models.SysProjectReq, old_row: models.SysProjectReq, logic_row: LogicRow):
    """
    Populate matched_project_id, confidence, reason, request_text.
    Works in three modes:
      - Test context (config/ai_test_context.yaml present): use configured match
      - OpenAI available: LLM ranking with contractor history
      - Fallback: token-overlap scoring
    """
    if not logic_row.is_inserted():
        return

    description   = row.description or ""
    contractor_id = row.contractor_id
    session       = logic_row.session

    # ── collect active projects ──────────────────────────────────────────
    active_projects = (
        session.query(models.Project)
        .join(models.ProjectFundingDefinition,
              models.Project.project_funding_definition_id == models.ProjectFundingDefinition.id)
        .filter(models.ProjectFundingDefinition.is_active == 1)
        .all()
    )

    if not active_projects:
        logic_row.log("AI project match: no active projects found")
        row.reason       = "No active projects available"
        row.request_text = f"description='{description}', contractor_id={contractor_id}"
        return

    project_names = [p.name for p in active_projects]

    # ── contractor history ───────────────────────────────────────────────
    history_note = ""
    if contractor_id:
        recent = (
            session.query(models.Charge)
            .join(models.Project, models.Charge.project_id == models.Project.id)
            .filter(models.Charge.contractor_id == contractor_id)
            .order_by(models.Charge.created_on.desc())
            .limit(10)
            .all()
        )
        if recent:
            seen = {}
            for c in recent:
                pname = c.project.name if c.project else "?"
                seen[pname] = seen.get(pname, 0) + 1
            history_note = "Contractor past projects: " + ", ".join(
                f"{n}(×{cnt})" for n, cnt in seen.items()
            )

    project_summary = "; ".join(project_names)
    row.request_text = (
        f"Match description='{description}' "
        f"to active projects=[{project_summary}]. "
        f"{history_note}"
    )
    logic_row.log(f"AI project match request: {row.request_text[:120]}")

    # ── check for test context ───────────────────────────────────────────
    try:
        project_root  = Path(__file__).resolve().parent.parent.parent.parent.parent
        context_file  = project_root / "config" / "ai_test_context.yaml"
        if context_file.exists():
            import yaml
            with open(str(context_file), "r") as f:
                test_ctx = yaml.safe_load(f)
            matched_name = test_ctx.get("matched_project_name")
            if matched_name:
                for p in active_projects:
                    if p.name == matched_name:
                        row.matched_project_id = p.id
                        row.confidence         = 1.0
                        row.reason             = f"TEST MODE: forced match to '{matched_name}'"
                        logic_row.log(f"AI project match (test): {row.reason}")
                        return
    except Exception:
        pass

    # ── try OpenAI ───────────────────────────────────────────────────────
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
            prompt = (
                f"You are a project matching assistant.\n"
                f"A contractor submitted this description: '{description}'\n"
                f"Active projects: {project_names}\n"
                f"{history_note}\n"
                f"Return JSON: {{\"best_match\": \"<project name>\", "
                f"\"confidence\": <0.0-1.0>, \"reason\": \"<short explanation>\"}}"
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0
            )
            result = json.loads(response.choices[0].message.content)
            best_name  = result.get("best_match", "")
            confidence = float(result.get("confidence", 0))
            reason_txt = result.get("reason", "")
            for p in active_projects:
                if p.name == best_name:
                    row.matched_project_id = p.id
                    row.confidence         = confidence
                    row.reason             = f"AI: {reason_txt}"
                    logic_row.log(f"AI project match (OpenAI): {best_name} ({confidence:.2f})")
                    return
        except Exception as e:
            logic_row.log(f"AI project match OpenAI failed: {e}")

    # ── fallback: token-overlap scoring ─────────────────────────────────
    desc_tokens = set(description.lower().split())

    def score(project: models.Project) -> float:
        name_tokens  = set(project.name.lower().split())
        overlap      = len(desc_tokens & name_tokens)
        history_bump = 0.0
        if contractor_id and history_note and project.name in history_note:
            history_bump = 0.5
        return overlap + history_bump

    best     = max(active_projects, key=score)
    best_scr = score(best)
    row.matched_project_id = best.id
    row.confidence         = min(1.0, best_scr / max(len(desc_tokens), 1))
    row.reason             = (
        f"Fallback token match: '{best.name}' (score={best_scr:.1f}). "
        f"{history_note}"
    )
    logic_row.log(f"AI project match (fallback): {best.name} (score={best_scr:.1f})")


# ── Wrapper ───────────────────────────────────────────────────────────────────

def get_project_from_ai(description: str, contractor_id, logic_row: LogicRow) -> models.SysProjectReq:
    """
    Wrapper: inserts a SysProjectReq, which triggers select_project_via_ai.
    Returns the populated request object so the caller can read matched_project_id.
    """
    req_lr  = logic_row.new_logic_row(models.SysProjectReq)
    req     = req_lr.row
    req.description   = description
    req.contractor_id = contractor_id
    req_lr.insert(reason="AI project identification")
    logic_row.log(f"SysProjectReq result: project_id={req.matched_project_id}, "
                  f"confidence={req.confidence}, reason={req.reason}")
    return req


# ── Early event on Charge: auto-identify project when project_id is missing ──

def identify_project_for_charge(row: models.Charge, old_row: models.Charge, logic_row: LogicRow):
    """
    If a Charge is inserted without a project_id but with a description and
    contractor_id, use AI to identify the project automatically.
    """
    if logic_row.is_deleted():
        return
    if not logic_row.is_inserted():
        return
    if row.project_id is not None:
        return  # project already specified — nothing to do
    if not row.description:
        return  # no description to match on

    logic_row.log(f"Charge has no project_id; attempting AI project identification "
                  f"for description='{row.description}'")
    req = get_project_from_ai(
        description=row.description,
        contractor_id=row.contractor_id,
        logic_row=logic_row
    )
    if req.matched_project_id:
        row.project_id = req.matched_project_id
        # Explicitly load the relationship so the downstream constraint can traverse it
        row.project = logic_row.session.get(models.Project, req.matched_project_id)
        logic_row.log(f"project_id set to {row.project_id} ({row.project.name}) via AI (confidence={req.confidence:.2f})")
    else:
        logic_row.log("AI project identification returned no match — charge will fail constraint")


def declare_logic():
    """
    Registers only the SysProjectReq handler here.

    The Charge early_row_event (identify_project_for_charge) is registered in
    charge_distribution.py BEFORE the Allocate declaration — that explicit
    ordering is necessary because Allocate also uses an EarlyRowEvent on Charge
    and events fire in registration order.
    """
    # AI handler fires when a SysProjectReq is inserted (order-independent)
    Rule.early_row_event(on_class=models.SysProjectReq, calling=select_project_via_ai)
