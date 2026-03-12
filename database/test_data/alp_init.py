#!/usr/bin/env python
import os, logging, logging.config, sys
from config import server_setup
import api.system.api_utils as api_utils
from flask import Flask
import logging
import config.config as config

os.environ["PROJECT_DIR"] = os.environ.get("PROJECT_DIR", os.path.abspath(os.path.dirname(__file__)))

app_logger = server_setup.logging_setup()
app_logger.setLevel(logging.INFO) 

current_path = os.path.abspath(os.path.dirname(__file__))
sys.path.extend([current_path, '.'])

flask_app = Flask("API Logic Server", template_folder='ui/templates')
flask_app.config.from_object(config.Config)
flask_app.config.from_prefixed_env(prefix="APILOGICPROJECT")

args = server_setup.get_args(flask_app)

server_setup.api_logic_server_setup(flask_app, args)

from database.models import *
import safrs
from datetime import date
import os
os.environ['AGGREGATE_DEFAULTS'] = 'True'

with flask_app.app_context():
    safrs.DB.create_all()
    session = safrs.DB.session

    # ── Contractors ────────────────────────────────────────────────────────
    acme   = Contractor(name="Acme Road Builders")
    summit = Contractor(name="Summit Construction")
    session.add_all([acme, summit])
    session.flush()

    # ── Departments ────────────────────────────────────────────────────────
    roads  = Department(name="Roads Department")
    infra  = Department(name="Infrastructure Department")
    session.add_all([roads, infra])
    session.flush()

    # ── GL Accounts ────────────────────────────────────────────────────────
    gl_r_labor = GlAccount(department_id=roads.id,  account_code="R-LAB", name="Roads Labour")
    gl_r_equip = GlAccount(department_id=roads.id,  account_code="R-EQP", name="Roads Equipment")
    gl_i_admin = GlAccount(department_id=infra.id,  account_code="I-ADM", name="Infra Admin")
    gl_i_ops   = GlAccount(department_id=infra.id,  account_code="I-OPS", name="Infra Operations")
    session.add_all([gl_r_labor, gl_r_equip, gl_i_admin, gl_i_ops])
    session.flush()

    # ── Dept Charge Definitions ────────────────────────────────────────────
    # Roads: 60% Labour, 40% Equipment  → total=100, is_active=1 (set by rules)
    roads_def = DeptChargeDefinition(department_id=roads.id, name="Roads Standard Allocation")
    session.add(roads_def)
    session.flush()
    session.add_all([
        DeptChargeDefinitionLine(dept_charge_definition_id=roads_def.id, gl_account_id=gl_r_labor.id, percent=60),
        DeptChargeDefinitionLine(dept_charge_definition_id=roads_def.id, gl_account_id=gl_r_equip.id, percent=40),
    ])

    # Infra: 30% Admin, 70% Operations → total=100, is_active=1 (set by rules)
    infra_def = DeptChargeDefinition(department_id=infra.id, name="Infra Standard Allocation")
    session.add(infra_def)
    session.flush()
    session.add_all([
        DeptChargeDefinitionLine(dept_charge_definition_id=infra_def.id, gl_account_id=gl_i_admin.id, percent=30),
        DeptChargeDefinitionLine(dept_charge_definition_id=infra_def.id, gl_account_id=gl_i_ops.id,   percent=70),
    ])

    # ── Project Funding Definitions ────────────────────────────────────────
    # Highway fund: 60% Roads, 40% Infra → total=100, is_active=1 (set by rules)
    hwy_fund = ProjectFundingDefinition(name="Highway Project Fund")
    session.add(hwy_fund)
    session.flush()
    session.add_all([
        ProjectFundingLine(project_funding_definition_id=hwy_fund.id,
                           department_id=roads.id, dept_charge_definition_id=roads_def.id, percent=60),
        ProjectFundingLine(project_funding_definition_id=hwy_fund.id,
                           department_id=infra.id, dept_charge_definition_id=infra_def.id, percent=40),
    ])

    # Bridge fund: 50% Roads, 50% Infra → total=100, is_active=1 (set by rules)
    bridge_fund = ProjectFundingDefinition(name="Bridge Maintenance Fund")
    session.add(bridge_fund)
    session.flush()
    session.add_all([
        ProjectFundingLine(project_funding_definition_id=bridge_fund.id,
                           department_id=roads.id, dept_charge_definition_id=roads_def.id, percent=50),
        ProjectFundingLine(project_funding_definition_id=bridge_fund.id,
                           department_id=infra.id, dept_charge_definition_id=infra_def.id, percent=50),
    ])

    # ── Projects ──────────────────────────────────────────────────────────
    hwy_1  = Project(name="Highway 1 Resurfacing",   project_funding_definition_id=hwy_fund.id)
    hwy_9  = Project(name="Highway 9 Widening",      project_funding_definition_id=hwy_fund.id)
    bridge = Project(name="Main Street Bridge Repair", project_funding_definition_id=bridge_fund.id)
    session.add_all([hwy_1, hwy_9, bridge])
    session.flush()

    session.commit()
    print("✅  Seed data loaded successfully")
    print(f"  Contractors: {session.query(Contractor).count()}")
    print(f"  Departments: {session.query(Department).count()}")
    print(f"  GL Accounts: {session.query(GlAccount).count()}")
    print(f"  DeptChargeDefinitions: {session.query(DeptChargeDefinition).count()}")
    print(f"  DeptChargeDefinitionLines: {session.query(DeptChargeDefinitionLine).count()}")
    print(f"  ProjectFundingDefinitions: {session.query(ProjectFundingDefinition).count()}")
    print(f"  ProjectFundingLines: {session.query(ProjectFundingLine).count()}")
    print(f"  Projects: {session.query(Project).count()}")

