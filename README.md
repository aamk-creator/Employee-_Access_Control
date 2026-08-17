# Employee Access Control System

Odoo 19 based internal system for managing employee access requests, approvals, vendor provisioning, and access lifecycle tracking.

## Project Status

- Core module: `employee_access_control`
- Platform: Odoo 19
- Current progress: about 90%
- Current focus: status display fixes and user status updates in the request form

## Repository Structure

- `employee_access_control/` - custom Odoo module
- `scripts/` - helper PowerShell scripts
- `odoo.conf.example` - safe sample Odoo configuration
- `requirements.txt` - Python dependencies entrypoint

## Main Features

- Employee access request form
- Approval workflow
- Vendor ticket workflow
- Request-based vendor ticket reference such as `REQ2608-0249`
- Vendor email compose flow from the ticket page
- Chatter history for vendor communication and notifications

## Requirements

- Python 3.12 recommended
- PostgreSQL
- Windows PowerShell

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Install Odoo 19 source separately, then update your local `odoo.conf` `addons_path` and `PYTHONPATH` to match your environment.

## Local Configuration

Use `odoo.conf.example` as the base for your local `odoo.conf`.

Important defaults:

- HTTP port: `8069`
- Database: `employee_access_control_dev`
- Data directory: `.odoo-data/`

## Run the Project

Start Odoo with the provided script:

```powershell
.\scripts\start_odoo.ps1
```

Start Odoo in background:

```powershell
.\scripts\start_odoo_background.ps1
```

Stop Odoo:

```powershell
.\scripts\stop_odoo.ps1
```

Open in browser:

```text
http://localhost:8069
```

## Install or Update the Module

Use the helper script:

```powershell
.\scripts\install_module.ps1
```

Or run Odoo manually with update:

```powershell
$env:PYTHONPATH='C:\Employee Access Control System\odoo-19.0.post20260812'
.\.venv\Scripts\python.exe -m odoo server -c .\odoo.conf -d employee_access_control_dev -u employee_access_control
```

## Run Tests

```powershell
$env:PYTHONPATH='C:\Employee Access Control System\odoo-19.0.post20260812'
.\.venv\Scripts\python.exe -m odoo server -c .\odoo.conf -d employee_access_control_dev -u employee_access_control --test-enable --test-tags /employee_access_control --stop-after-init
```

## GitHub Notes

Before pushing to GitHub:

- keep real `odoo.conf` local only
- use `odoo.conf.example` in the repository
- confirm no local logs or runtime data are included
- confirm `.venv/` and `.odoo-data/` are ignored
- keep the local Odoo core source outside GitHub unless you intentionally want to vendor it

Recommended next step:

- document the exact Odoo 19 source package or repository your team should download locally

## License

Custom module is declared as `LGPL-3` in the Odoo manifest.
