-- Domain schema for allo_dept_gl project
-- Created: 2026-03-11

-- Contractors who submit charges
CREATE TABLE contractor (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

-- Departments
CREATE TABLE department (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

-- GL Accounts owned by a department
CREATE TABLE gl_account (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES department(id),
    account_code  TEXT    NOT NULL,
    name          TEXT    NOT NULL
);

-- Department Charge Definition header
-- total_percent = sum of lines (derived); is_active = 1 when total_percent == 100 (derived)
CREATE TABLE dept_charge_definition (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES department(id),
    name          TEXT    NOT NULL,
    total_percent NUMERIC(7,4) DEFAULT 0,
    is_active     INTEGER      DEFAULT 0
);

-- Lines: how each GL account is weighted within the definition
CREATE TABLE dept_charge_definition_line (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_charge_definition_id INTEGER NOT NULL REFERENCES dept_charge_definition(id),
    gl_account_id             INTEGER NOT NULL REFERENCES gl_account(id),
    percent                   NUMERIC(7,4) NOT NULL DEFAULT 0
);

-- Project Funding Definition header
-- total_percent = sum of lines (derived); is_active = 1 when total_percent == 100 (derived)
CREATE TABLE project_funding_definition (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    total_percent NUMERIC(7,4) DEFAULT 0,
    is_active     INTEGER      DEFAULT 0
);

-- Lines: which dept funds what % and which charge definition it uses
CREATE TABLE project_funding_line (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_funding_definition_id INTEGER NOT NULL REFERENCES project_funding_definition(id),
    department_id                 INTEGER NOT NULL REFERENCES department(id),
    dept_charge_definition_id     INTEGER NOT NULL REFERENCES dept_charge_definition(id),
    percent                       NUMERIC(7,4) NOT NULL DEFAULT 0
);

-- Projects assigned to a funding definition
CREATE TABLE project (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    name                          TEXT    NOT NULL,
    project_funding_definition_id INTEGER REFERENCES project_funding_definition(id)
);

-- Charges posted against a project
CREATE TABLE charge (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id               INTEGER REFERENCES project(id),
    contractor_id            INTEGER REFERENCES contractor(id),
    description              TEXT,
    amount                   NUMERIC(15,2) NOT NULL DEFAULT 0,
    total_distributed_amount NUMERIC(15,2) DEFAULT 0,
    created_on               DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Level-1 allocation: charge to department
CREATE TABLE charge_dept_allocation (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    charge_id                 INTEGER NOT NULL REFERENCES charge(id),
    project_funding_line_id   INTEGER NOT NULL REFERENCES project_funding_line(id),
    department_id             INTEGER NOT NULL REFERENCES department(id),
    dept_charge_definition_id INTEGER NOT NULL REFERENCES dept_charge_definition(id),
    percent                   NUMERIC(7,4) DEFAULT 0,
    amount                    NUMERIC(15,2) DEFAULT 0
);

-- Level-2 allocation: department allocation to GL account
CREATE TABLE charge_gl_allocation (
    id                             INTEGER PRIMARY KEY AUTOINCREMENT,
    charge_dept_allocation_id      INTEGER NOT NULL REFERENCES charge_dept_allocation(id),
    dept_charge_definition_line_id INTEGER NOT NULL REFERENCES dept_charge_definition_line(id),
    gl_account_id                  INTEGER NOT NULL REFERENCES gl_account(id),
    percent                        NUMERIC(7,4) DEFAULT 0,
    amount                         NUMERIC(15,2) DEFAULT 0
);

-- AI Request Pattern: fuzzy project identification from contractor + description
CREATE TABLE sys_project_req (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    contractor_id      INTEGER REFERENCES contractor(id),
    description        TEXT    NOT NULL,
    matched_project_id INTEGER REFERENCES project(id),
    confidence         REAL,
    reason             TEXT,
    request_text       TEXT,
    created_on         DATETIME DEFAULT CURRENT_TIMESTAMP
);
