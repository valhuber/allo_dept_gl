"""
Charge Distribution — Two-Level Cascade Allocation
====================================================
Level 1: Charge → ChargeDeptAllocation (one row per ProjectFundingLine)
Level 2: ChargeDeptAllocation → ChargeGlAllocation (one row per DeptChargeDefinitionLine)

🚨 Cascade timing pitfall: Level-2 allocator fires as an EarlyRowEvent on the
Level-1 row BEFORE Rule.copy/Rule.formula run on that row.  Both allocators
pre-compute percent and amount so the downstream formulas see the correct values.

Constraint: a Charge may only be posted if the Project's
ProjectFundingDefinition is active (is_active == 1).
"""
from decimal import Decimal
from logic_bank.logic_bank import Rule
from logic_bank.extensions.allocate import Allocate
from logic_bank.exec_row_logic.logic_row import LogicRow
from database import models
from logic.logic_discovery.ai_requests.project_identification import identify_project_for_charge


# ── Recipients ────────────────────────────────────────────────────────────────

def funding_lines_for_charge(provider: LogicRow):
    """Level-1: All ProjectFundingLines for the charge's project funding definition."""
    project = provider.row.project
    pfd = project.project_funding_definition if project else None
    if pfd is None:
        return []
    return provider.session.query(models.ProjectFundingLine)\
        .filter(models.ProjectFundingLine.project_funding_definition_id == pfd.id)\
        .all()


def charge_def_lines_for_dept_allocation(provider: LogicRow):
    """Level-2: DeptChargeDefinitionLines for this dept allocation's charge definition."""
    dept_alloc = provider.row
    if dept_alloc.dept_charge_definition_id is None:
        return []
    return provider.session.query(models.DeptChargeDefinitionLine)\
        .filter(models.DeptChargeDefinitionLine.dept_charge_definition_id ==
                dept_alloc.dept_charge_definition_id)\
        .all()


# ── Custom allocators ─────────────────────────────────────────────────────────

def allocate_charge_to_dept(allocation_logic_row, provider_logic_row) -> bool:
    """
    Level-1: pre-compute percent AND amount BEFORE insert so the Level-2
    allocator (which fires as an EarlyRowEvent before copy/formula) reads
    the correct amount from the ChargeDeptAllocation row.
    """
    allocation   = allocation_logic_row.row
    funding_line = allocation_logic_row.row.project_funding_line   # set by link()
    charge       = provider_logic_row.row

    allocation.department_id             = funding_line.department_id
    allocation.dept_charge_definition_id = funding_line.dept_charge_definition_id
    allocation.percent = funding_line.percent
    allocation.amount  = (
        Decimal(str(charge.amount or 0))
        * Decimal(str(funding_line.percent or 0))
        / Decimal(100)
    )
    allocation_logic_row.insert(reason="Allocate charge to dept")
    return True  # always process all recipients (non-draining)


def allocate_dept_to_gl(allocation_logic_row, provider_logic_row) -> bool:
    """
    Level-2: provider (ChargeDeptAllocation) amount is already pre-set by the
    Level-1 allocator above, so we can safely read it here.
    """
    allocation = allocation_logic_row.row
    defn_line  = allocation_logic_row.row.dept_charge_definition_line  # set by link()
    dept_alloc = provider_logic_row.row

    allocation.gl_account_id = defn_line.gl_account_id
    allocation.percent = defn_line.percent
    allocation.amount  = (
        Decimal(str(dept_alloc.amount or 0))
        * Decimal(str(defn_line.percent or 0))
        / Decimal(100)
    )
    allocation_logic_row.insert(reason="Allocate dept amount to GL")
    return True  # non-draining


# ── Logic declarations ────────────────────────────────────────────────────────

def declare_logic():

    # ── AI project identification — registered FIRST so it fires before Allocate's
    #    internal EarlyRowEvent on Charge (events fire in registration order).
    #    The SysProjectReq handler is registered in project_identification.declare_logic().
    Rule.early_row_event(on_class=models.Charge, calling=identify_project_for_charge)

    # Constraint: project must have an active funding definition before a charge is posted
    Rule.constraint(
        validate=models.Charge,
        as_condition=lambda row: (
            row.project is not None
            and row.project.project_funding_definition is not None
            and row.project.project_funding_definition.is_active == 1
        ),
        error_msg="Charge rejected: Project '{row.project.name if row.project else '?'}' "
                  "does not have an active Project Funding Definition (must cover exactly 100%)"
    )

    # ── Level-1 companion rules ──────────────────────────────────────────────
    Rule.copy(derive=models.ChargeDeptAllocation.percent,
              from_parent=models.ProjectFundingLine.percent)

    Rule.formula(derive=models.ChargeDeptAllocation.amount,
                 as_expression=lambda row:
                     row.charge.amount * row.percent / Decimal(100)
                     if row.charge and row.percent is not None else Decimal(0))

    Rule.sum(derive=models.Charge.total_distributed_amount,
             as_sum_of=models.ChargeDeptAllocation.amount)

    # ── Level-2 companion rules ──────────────────────────────────────────────
    Rule.copy(derive=models.ChargeGlAllocation.percent,
              from_parent=models.DeptChargeDefinitionLine.percent)

    Rule.formula(derive=models.ChargeGlAllocation.amount,
                 as_expression=lambda row:
                     row.charge_dept_allocation.amount * row.percent / Decimal(100)
                     if row.charge_dept_allocation and row.percent is not None else Decimal(0))

    # ── Level-1 Allocate: Charge → ChargeDeptAllocation ─────────────────────
    Allocate(provider=models.Charge,
             recipients=funding_lines_for_charge,
             creating_allocation=models.ChargeDeptAllocation,
             while_calling_allocator=allocate_charge_to_dept)

    # ── Level-2 Allocate: ChargeDeptAllocation → ChargeGlAllocation ─────────
    # Cascade: fires automatically as an EarlyRowEvent on each ChargeDeptAllocation insert
    Allocate(provider=models.ChargeDeptAllocation,
             recipients=charge_def_lines_for_dept_allocation,
             creating_allocation=models.ChargeGlAllocation,
             while_calling_allocator=allocate_dept_to_gl)
