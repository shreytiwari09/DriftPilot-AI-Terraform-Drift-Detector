# Real-Azure demo (prepared, not applied): one storage account and one firewall rule list

This folder builds **a very small, real set of Azure resources** in your Azure for Students subscription, so DriftPilot can be shown on something real, not
only on mocks. It exists because the free AWS account cannot create anything (its account-wide block, a *service control policy*, denies it).
**Nothing here has been applied.** It was written and checked offline only (`terraform validate`, an offline `terraform test` with a mocked Azure,
unit tests for the rules and the helper script). The first time anything real happens is when *you* run `scripts/azure_demo.sh apply` and type the location to confirm.

## Read this first: what was and was not checked

- **Checked offline:** the Terraform is valid, the plan has exactly the three resources below, the storage account name is lowercase and 14 characters
  (the limit is 24), the firewall rule refuses `0.0.0.0/0` and `*`, the helper script refuses to run without a login, and DriftPilot's Azure rules give
  the expected verdicts on hand-written plan files.
- **NOT checked (nobody has created anything on your subscription yet):** that Azure accepts every setting exactly as written, and that no *other* policy blocks a
  storage account or a network security group. Azure for Students restricts **regions** (this one is known: five regions, see "Check your subscription") and may restrict **services** with an
  *Azure Policy* (a subscription-wide rule that says what may be created). See "If apply is denied by an Azure Policy" below, and "Check your subscription" first.
- Attribute names in DriftPilot's Azure rules (`allow_nested_items_to_be_public`, `https_traffic_only_enabled`, `min_tls_version`, `security_rule`)
  were read from the pinned provider's own schema (`terraform providers schema -json`), but a live refresh has not been seen yet. If the **first scan,
  before you change anything,** reports something, that is real information about how Azure reports the resources: send it to me, do not ignore it.

## What it creates

| Resource | Name | Why | Settings that matter |
| --- | --- | --- | --- |
| Resource group | `rg-driftpilot-demo-<8 random characters>` | a folder that holds everything below; deleting it deletes all of it | tags `demo=driftpilot`, `team=platform` |
| Storage account | `dpdemo<8 random characters>` (14 characters, lowercase) | the thing hand changes (a), (b), (c), (e) act on | Standard, LRS (three copies in one datacentre: the cheapest), StorageV2, **https only on**, **minimum TLS 1.2**, **anonymous blob access off** |
| Network security group | `nsg-driftpilot-demo` | a firewall rule list; hand change (d) adds a rule to it | one rule: allow **SSH (port 22) from your own IP address only** (`my_ip_cidr`, a /32) |

That is all: **three things**. No virtual machine, no public IP address, no database, no Key Vault, no gateway, no disk, no container with files in it.
The network security group is not attached to anything (there is no virtual network); it only exists so DriftPilot has a firewall rule list to watch.
The random suffix is there because storage account names are shared by everybody in the world.

## What it costs (my estimate, labelled)

**Almost nothing.** A resource group and a network security group are free. An *empty* Standard LRS storage account has no capacity charge; the only
charges are per request, and Terraform and DriftPilot make a few dozen small requests (a tiny fraction of a cent). This is my estimate from memory of the
Azure price list, not a quote: check it with the *Azure pricing calculator*. Your Azure for Students credit (about $100) is far beyond that.
Even so, **destroy it when you are done** (`scripts/azure_demo.sh destroy`): "nothing left" is a good habit and `check-clean` proves it.

## Before you start (once)

1. **Tools** (macOS): the Azure CLI (installed at `~/.local/bin/az`; make sure `~/.local/bin` is on your PATH: `az --version`) and Terraform (installed).
2. **Log in** with the student account. A browser window opens; sign in and come back to the terminal:

   ```bash
   az login
   az account show --query "{name:name, id:id, state:state}" --output table     # read-only: which subscription is active
   az account list --output table                                              # only if you have more than one
   az account set --subscription "Azure for Students"                          # only if the active one is not the student one
   ```

   `az login` stores a sign-in on this laptop (in `~/.azure`). The demo uses that sign-in: **no password, secret or key goes into any file or command.**
   Never paste a secret into a chat or a screenshot. (Scanning uses the same login, which is allowed to change things. DriftPilot only ever runs a
   refresh-only plan and never applies; a separate read-only identity is not set up here.)
3. **Check your subscription** (portal, five minutes, worth doing before the first apply): go to <https://portal.azure.com>, search **Subscriptions**, open yours.
   - **Overview:** the name (*Azure for Students*), the **subscription ID** and **Status: Active**. If it says *Disabled* or *Expired*, nothing will work.
   - **Credits:** the remaining credit (about $100 at the start). It may sit under **Cost Management + Billing**, then **Credits**, depending on your account. Note the number now and again after the demo.
   - **Allowed regions:** in the left menu choose **Policies** (under *Settings*), then **Compliance**. Your subscription has a policy *Allowed resource deployment regions*
     (put there by Azure for Students, **not by this demo**). It allows exactly five regions, and nothing can be created anywhere else:
     **`koreacentral`, `indiasouthcentral`, `eastasia`, `malaysiawest`, `indonesiacentral`**. (Read-only check of the list was done on your subscription.)
     That is why the default region is `koreacentral` and why `centralindia`, `westeurope` and every other region are refused by Terraform (`variables.tf`) and by the script.
     Read-only command line alternative: `az policy assignment list --query "[].{policy:displayName, locations:parameters.listOfAllowedLocations.value}" --output json`.
   - Anything else in that Policies list that restricts **resource types** (for example storage accounts or network security groups) is worth noting: send me its name.
4. **Services registered** (a one-time switch per Azure service). A new subscription has not switched on every service yet. On yours, `Microsoft.Storage` and `Microsoft.Network`
   (the two the demo needs) were last seen as `NotRegistered`; your login (role *Contributor*) is allowed to register services. `scripts/azure_demo.sh plan` prints their state.
   Terraform is set to register **only those two** (not its usual long list) the first time it runs, but registering them yourself first is clearer and takes a minute:

   ```bash
   az provider register --namespace Microsoft.Storage
   az provider register --namespace Microsoft.Network
   az provider show --namespace Microsoft.Storage --query registrationState --output tsv    # repeat until it says Registered
   az provider show --namespace Microsoft.Network --query registrationState --output tsv
   ```

   This changes your subscription (it switches a free service on), so it is the one command here that is not read-only; it creates nothing and costs nothing.

5. **Your settings file.** Copy `terraform.tfvars.example` to `terraform.tfvars` (gitignored) and fill it in:

   ```bash
   cp demo/azure/terraform.tfvars.example demo/azure/terraform.tfvars
   curl -s https://checkip.amazonaws.com        # your public IP address; write it into the file as  my_ip_cidr = "<that address>/32"
   ```

   - `my_ip_cidr` is required. Only that address may reach SSH. `0.0.0.0/0` and `*` are refused by Terraform and by the tests.
   - `location` (optional, default `koreacentral`): one of the five allowed regions above; anything else is refused. To use another of the five, put it in this file, not only in
     `DEMO_LOCATION`, because `driftpilot scan` reads the file too and both must use the same region.
   - `subscription_id` (optional): leave it out. The script uses the subscription `az login` is on.

## If apply is denied by an Azure Policy

If `scripts/azure_demo.sh apply` stops with `RequestDisallowedByPolicy`, `Policy`, `not allowed` or `The resource ... was disallowed by policy`, that is your
subscription's own rule, not a bug in the demo. **Stop. Do not try to remove, disable or get around the policy** (no exemptions, no other account, no other subscription).

1. Copy the **whole error text** (it names the policy and often lists the allowed regions) and send it to me. It contains no secret.
2. If the error says the **region** is not allowed, you may try again with another region **from that list** (the five above), only by changing `location` in `terraform.tfvars`
   (the script asks you to type the new region name). Nothing else needs to change. Even an allowed region can be full for a service; that shows up as a different error: send it too.
3. If it says a **resource type** is not allowed, there is nothing to change in the demo: show the recorded runs and the mock tests instead
   (`.venv/bin/pytest tests/test_azure_rules.py tests/test_azure_demo_script.py` need no Azure) and send me the error.
4. Either way, make sure nothing half-created is left: `scripts/azure_demo.sh check-clean`. If it lists something, `scripts/azure_demo.sh destroy` removes what Terraform created.

## Everything you will run, in order

The full step by step, with the hand changes click by click, is in [`RUNBOOK.md`](RUNBOOK.md). In short:

```bash
az login
scripts/azure_demo.sh plan               # preview, creates nothing
scripts/azure_demo.sh apply              # type the location when asked
driftpilot scan --dir demo/azure --no-llm        # baseline: "No drift detected"
# ... make the hand changes in the portal (RUNBOOK.md, a to e) ...
driftpilot scan --dir demo/azure --no-llm        # DriftPilot finds them
# ... revert them (RUNBOOK.md) ...
driftpilot scan --dir demo/azure --no-llm        # clean again
scripts/azure_demo.sh destroy            # type the location when asked
scripts/azure_demo.sh check-clean        # must say "Clean"
```

## Check that nothing is left

`scripts/azure_demo.sh check-clean` fails (exit 1) if it finds a resource group named `rg-driftpilot-demo-*` (or tagged `demo=driftpilot`), anything inside it, or a
`dpdemo*` storage account anywhere in the subscription. If it cannot read Azure it stops with an error instead of saying "clean". With your own eyes: portal,
**Resource groups**: no `rg-driftpilot-demo-...`. If something is stuck, you can delete a resource group by hand: portal, the group, **Delete resource group**,
type its name. (That is the only deletion that is not done by Terraform.)

## Files in this folder

| File | What it is |
| --- | --- |
| `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` | the Terraform code (azurerm 4, pinned) |
| `.terraform.lock.hcl` | pins the exact provider versions; committed on purpose |
| `terraform.tfvars.example` | settings template; your copy `terraform.tfvars` holds your IP and is gitignored |
| `.driftpilot.yml` | DriftPilot settings for this demo (advise mode: issues only) |
| `tests/scope.tftest.hcl` | offline `terraform test` with a mocked Azure |
| `RUNBOOK.md` | the demo, step by step |
