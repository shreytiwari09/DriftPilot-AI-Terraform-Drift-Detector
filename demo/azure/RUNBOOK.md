# Runbook: the real-Azure demo, in order

Run every command from the **repo root**. First time here? Do "Before you start" in `README.md` first (login, check your subscription and allowed regions,
`terraform.tfvars`). **Never paste a password, key or secret into a chat, a file or a screenshot.**

What happens, in one line: **plan** (preview) -> **apply** (create 3 things) -> **scan** (baseline, clean) -> **change things by hand in the portal** ->
**scan** (DriftPilot finds them) -> **revert** (put them back) -> **scan** (clean again) -> **destroy** -> **check-clean**.

**Drift** means the real cloud no longer matches what the Terraform code says. DriftPilot finds it by asking Terraform for a *refresh-only plan*: "look at
the real resources and tell me how they differ from what you recorded". It never changes anything itself.

## 0. Every session: set up the shell (one terminal, keep using it)

```bash
source .venv/bin/activate
uv pip install --python .venv/bin/python -e ".[dev,demo]"          # first time only
az login                                                          # browser window; use the student account (skip if you did it today)
az account show --query "{name:name, id:id}" --output table      # read-only: shows the subscription Azure will use
export ARM_SUBSCRIPTION_ID=$(az account show --query id --output tsv)   # makes Terraform and DriftPilot use that same subscription
```

**One time only: switch on the two Azure services the demo uses** (they were `NotRegistered` on your subscription; this creates nothing and costs nothing, and your login may do it):

```bash
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.Network
az provider show --namespace Microsoft.Storage --query registrationState --output tsv    # repeat until: Registered
az provider show --namespace Microsoft.Network --query registrationState --output tsv    # repeat until: Registered
```

**Region:** your subscription's Azure Policy allows only `koreacentral` (the default here), `indiasouthcentral`, `eastasia`, `malaysiawest` and `indonesiacentral`.
That rule comes from Azure for Students, not from this demo; Terraform and the script refuse any other region.

## 1. Create it (costs almost nothing)

```bash
scripts/azure_demo.sh plan      # also prints whether Microsoft.Storage and Microsoft.Network are Registered. Read the plan: 4 to add (random suffix, resource group, storage account, network security group). Nothing is created.
scripts/azure_demo.sh apply     # shows the subscription and location; type the location when asked. About 1 to 2 minutes.
scripts/azure_demo.sh status    # lists rg-driftpilot-demo-xxxxxxxx and its two resources
```

**This is the first write ever tried on this subscription (untested).** If `apply` stops with `RequestDisallowedByPolicy` or "not allowed", follow
"If apply is denied by an Azure Policy" in `README.md` (stop, send me the error, other region only through `location` in `terraform.tfvars`, never work around a policy).

Names for the commands below (read from Terraform's own records, nothing secret):

```bash
RG=$(terraform -chdir=demo/azure output -raw resource_group_name)
SA=$(terraform -chdir=demo/azure output -raw storage_account_name)
NSG=$(terraform -chdir=demo/azure output -raw network_security_group_name)
echo "$RG  $SA  $NSG"
```

## 2. Baseline scan (nothing changed yet)

```bash
driftpilot scan --dir demo/azure --no-llm        # expect: "No drift detected"
```

`--no-llm` means no Gemini key is needed: the rules decide everything in this demo. If this first scan reports something, **do not change anything**: copy the output and
send it to me (see "Read this first" in `README.md`).

## 3. Make drift by hand, then scan

There is **no script that changes Azure for you**: you make each change yourself in the portal (the point of drift is that a person changes things outside Terraform).
Every change has the portal steps, an optional `az` one-liner that does the same, how to put it back, and what DriftPilot should say.
Do one, scan, revert, then the next; or do all five and scan once (expect five findings).
After a change, **wait about a minute** before scanning, so Azure has applied it. Portal screens are renamed from time to time; if a label differs a little, look for the
closest one, or use the command line instead.

Open the portal at <https://portal.azure.com>. **Storage accounts** -> the account whose name starts with `dpdemo` is the storage account.
**Resource groups** -> `rg-driftpilot-demo-...` -> `nsg-driftpilot-demo` is the network security group.

### a) Allow public (anonymous) access to blobs

*Why it matters:* with this on, someone can later make a container readable by anyone on the internet without a key. No container exists in the demo, so nothing is actually exposed.

**Portal:** Storage accounts -> your `dpdemo...` account -> left menu **Settings** -> **Configuration** -> find **Allow Blob anonymous access** -> set it to **Enabled** -> click **Save** at the top.

**Or command line:**

```bash
az storage account update --name "$SA" --resource-group "$RG" --allow-blob-public-access true
```

**Expect from DriftPilot:** `allow_nested_items_to_be_public` **critical**, action **revert**, tag `public-storage`. The rule decides it and the AI may not play it down (never-soften list).

**Revert:** Configuration -> **Allow Blob anonymous access** -> **Disabled** -> **Save**, or

```bash
az storage account update --name "$SA" --resource-group "$RG" --allow-blob-public-access false
```

### b) Turn off "Secure transfer required"

*Why it matters:* with it off, the account accepts plain `http://` requests, which are not encrypted.

**Portal:** your `dpdemo...` account -> **Settings** -> **Configuration** -> **Secure transfer required** -> **Disabled** -> **Save**.

**Or command line:**

```bash
az storage account update --name "$SA" --resource-group "$RG" --https-only false
```

**Expect:** `https_traffic_only_enabled` **critical**, action **revert**. (Tag `encryption-at-rest`: DriftPilot has no "encryption in transit" tag, so this is the closest existing one.)

**Revert:** **Secure transfer required** -> **Enabled** -> **Save**, or `az storage account update --name "$SA" --resource-group "$RG" --https-only true`.

### c) Lower the minimum TLS version

*Why it matters:* TLS is the encryption on the connection; versions 1.0 and 1.1 are old and weak. The account should insist on 1.2 or newer.

**Portal:** your `dpdemo...` account -> **Settings** -> **Configuration** -> **Minimum TLS version** -> **Version 1.0** (or 1.1) -> **Save**.

**Or command line:**

```bash
az storage account update --name "$SA" --resource-group "$RG" --min-tls-version TLS1_0
```

**Heads-up (unverified):** Microsoft has been retiring TLS 1.0 and 1.1, so the portal or the command may refuse the old versions. If it does, skip (c) and tell me the message; the other four still work.

**Expect:** `min_tls_version` **high**, action **revert**. (Tag `encryption-at-rest`, the closest existing tag.)

**Revert:** **Minimum TLS version** -> **Version 1.2** -> **Save**, or `az storage account update --name "$SA" --resource-group "$RG" --min-tls-version TLS1_2`.

### d) Add a firewall rule that allows SSH from anywhere

*Why it matters:* SSH (port 22) is how people log in to servers. Allowing it from "Any" lets the whole internet try. No machine exists in the demo, so nothing is actually reachable.

**Portal:** Resource groups -> `rg-driftpilot-demo-...` -> `nsg-driftpilot-demo` -> left menu **Settings** -> **Inbound security rules** -> **+ Add**, then:
**Source** = *Any*; **Source port ranges** = `*`; **Destination** = *Any*; **Service** = *SSH* (this fills in port 22 and TCP); **Action** = *Allow*;
**Priority** = `110`; **Name** = `portal-ssh-any` -> **Add**.

**Or command line:**

```bash
az network nsg rule create --resource-group "$RG" --nsg-name "$NSG" --name portal-ssh-any \
  --priority 110 --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes '*' --source-port-ranges '*' \
  --destination-address-prefixes '*' --destination-port-ranges 22
```

**Expect:** `security_rule` **critical**, action **revert**, tag `network-exposure` (the rule decides it and the AI may not play it down).
DriftPilot reads the new rule's source (`*`, `Any`, `0.0.0.0/0` and `Internet` all count) and port (22, 3389, a range that contains them, or `*`).

**Revert:** NSG -> **Inbound security rules** -> tick `portal-ssh-any` -> **Delete**, or

```bash
az network nsg rule delete --resource-group "$RG" --nsg-name "$NSG" --name portal-ssh-any
```

### e) Edit a tag

*Why it matters:* tags are labels (who owns this, which team pays). A changed label is real drift but harmless: the lowest severity.

**Portal:** your `dpdemo...` account -> left menu **Tags** -> change the value of `team` from `platform` to `data-platform` -> **Apply**.

**Or command line** (this sets the account's whole tag list, so both tags are given):

```bash
az storage account update --name "$SA" --resource-group "$RG" --tags demo=driftpilot team=data-platform
```

**Expect:** `tags.team` **low**, action **codify** ("put the new value in the code, or revert it"). The rule decides it, no AI needed.

**Revert:** put `team` back to `platform` in **Tags** -> **Apply**, or `az storage account update --name "$SA" --resource-group "$RG" --tags demo=driftpilot team=platform`.

### Scan after the changes

```bash
driftpilot scan --dir demo/azure --no-llm
```

With all five changes made, expect these five findings: **three critical** (a, b, d), **one high** (c), **one low** (e). Each critical one is marked "never soften".
In `advise` mode (set in `.driftpilot.yml`) DriftPilot only reports; it never opens pull requests and never runs `terraform apply`.

### Revert, then scan again

Revert everything with the steps above, wait a minute, then:

```bash
driftpilot scan --dir demo/azure --no-llm        # expect: "No drift detected"
```

(If you would rather let Terraform do the reverting, `terraform -chdir=demo/azure apply -var location=<your location>` puts a, b, c, d and e back, because it makes
Azure match the code again. `scripts/azure_demo.sh plan` first shows what it would change.)

## 4. Clean up (do this the same day)

```bash
scripts/azure_demo.sh destroy        # lists what will go; type the location to confirm. About 1 to 2 minutes.
scripts/azure_demo.sh check-clean    # must say "Clean"; if not, it lists what is left
rm -f demo/azure/terraform.tfstate demo/azure/terraform.tfstate.backup    # only after a clean destroy
```

Then look with your own eyes: portal -> **Resource groups**: no `rg-driftpilot-demo-...`. Optional: look at your credit again (README, "Check your subscription") and compare with the number you noted before.

If any step fails half way, send me the output of `scripts/azure_demo.sh status` and `check-clean` and the exact error; the state file `demo/azure/terraform.tfstate` stays as it is.

## Troubleshooting

| What you see | What it means |
| --- | --- |
| `not logged in to Azure` | run `az login` again (the sign-in expires) |
| `RequestDisallowedByPolicy`, "not allowed" | an Azure Policy on the subscription: read "If apply is denied by an Azure Policy" in `README.md`. Stop and send me the error. |
| `MissingSubscriptionRegistration` | `az provider register --namespace Microsoft.Storage` (or `Microsoft.Network`), wait until `az provider show ... --query registrationState -o tsv` says `Registered`, run `apply` again |
| `location ... is not allowed by this subscription's Azure Policy` (from the script) or a `location` error from Terraform | use one of `koreacentral`, `indiasouthcentral`, `eastasia`, `malaysiawest`, `indonesiacentral` in `terraform.tfvars` |
| `StorageAccountAlreadyTaken` | extremely unlikely (random name); run `apply` again |
| `ARM_SUBSCRIPTION_ID ... is not the subscription 'az login' is using` | `unset ARM_SUBSCRIPTION_ID`, then export it again from `az account show` as in step 0 |
| the first scan already shows drift | do not change anything; send me the output (Azure reports some settings differently from how Terraform writes them) |
