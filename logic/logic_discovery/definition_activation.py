"""
Definition Activation Rules
============================
Both DeptChargeDefinition and ProjectFundingDefinition follow the same pattern:
  - total_percent  = sum of their line percents
  - is_active      = 1 when total_percent == 100, else 0
"""
from decimal import Decimal
from logic_bank.logic_bank import Rule
from database import models


def declare_logic():

    # ── DeptChargeDefinition ──────────────────────────────────────────────
    Rule.sum(derive=models.DeptChargeDefinition.total_percent,
             as_sum_of=models.DeptChargeDefinitionLine.percent)

    Rule.formula(derive=models.DeptChargeDefinition.is_active,
                 as_expression=lambda row: 1 if row.total_percent == Decimal('100') else 0)

    # ── ProjectFundingDefinition ──────────────────────────────────────────
    Rule.sum(derive=models.ProjectFundingDefinition.total_percent,
             as_sum_of=models.ProjectFundingLine.percent)

    Rule.formula(derive=models.ProjectFundingDefinition.is_active,
                 as_expression=lambda row: 1 if row.total_percent == Decimal('100') else 0)
