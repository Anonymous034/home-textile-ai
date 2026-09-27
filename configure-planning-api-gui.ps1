$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectRoot "backend\.env"
$planningEndpoint = "https://ark.cn-beijing.volces.com/api/v3/responses"
$planningModel = "doubao-seed-2-0-lite-260215"

$form = New-Object System.Windows.Forms.Form
$form.Text = "Configure Planning AI"
$form.ClientSize = New-Object System.Drawing.Size(560, 270)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(15, 18, 28)
$form.ForeColor = [System.Drawing.Color]::White

$title = New-Object System.Windows.Forms.Label
$title.Text = "Planning AI - Local Secure Setup"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 14, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(26, 22)
$title.Size = New-Object System.Drawing.Size(508, 32)
$form.Controls.Add($title)

$tip = New-Object System.Windows.Forms.Label
$tip.Text = "Paste only your Volcengine Ark API Key. Endpoint and vision model are configured automatically."
$tip.ForeColor = [System.Drawing.Color]::FromArgb(145, 165, 185)
$tip.Location = New-Object System.Drawing.Point(26, 61)
$tip.Size = New-Object System.Drawing.Size(508, 42)
$form.Controls.Add($tip)

$label = New-Object System.Windows.Forms.Label
$label.Text = "Volcengine Ark API Key (masked while typing)"
$label.Location = New-Object System.Drawing.Point(26, 112)
$label.Size = New-Object System.Drawing.Size(508, 22)
$form.Controls.Add($label)

$input = New-Object System.Windows.Forms.TextBox
$input.Location = New-Object System.Drawing.Point(26, 139)
$input.Size = New-Object System.Drawing.Size(508, 30)
$input.Font = New-Object System.Drawing.Font("Consolas", 10)
$input.UseSystemPasswordChar = $true
$input.BackColor = [System.Drawing.Color]::FromArgb(5, 9, 16)
$input.ForeColor = [System.Drawing.Color]::White
$form.Controls.Add($input)

$save = New-Object System.Windows.Forms.Button
$save.Text = "Save securely"
$save.Location = New-Object System.Drawing.Point(302, 202)
$save.Size = New-Object System.Drawing.Size(118, 40)
$save.BackColor = [System.Drawing.Color]::FromArgb(0, 185, 210)
$save.FlatStyle = "Flat"
$save.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $save
$form.Controls.Add($save)

$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = "Cancel"
$cancel.Location = New-Object System.Drawing.Point(430, 202)
$cancel.Size = New-Object System.Drawing.Size(104, 40)
$cancel.FlatStyle = "Flat"
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.CancelButton = $cancel
$form.Controls.Add($cancel)

$input.Focus()
$result = $form.ShowDialog()
if ($result -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }

$keyValue = $input.Text.Trim()
if ($keyValue.Length -lt 20 -or $keyValue -match "\s") {
  [System.Windows.Forms.MessageBox]::Show("Paste the complete API key copied from Ark API Key Management.", "Unable to save", "OK", "Warning") | Out-Null
  exit 1
}

$values = [ordered]@{}
if (Test-Path -LiteralPath $envPath) {
  foreach ($line in Get-Content -LiteralPath $envPath -Encoding utf8) {
    if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') { $values[$matches[1]] = $matches[2] }
  }
}
$values['DETAIL_PLAN_ENDPOINT'] = $planningEndpoint
$values['DETAIL_PLAN_MODEL'] = $planningModel
$values['DETAIL_PLAN_API_KEY'] = $keyValue
$values.Remove('BUYER_PLAN_ENDPOINT')
$values.Remove('BUYER_PLAN_MODEL')
$values.Remove('BUYER_PLAN_API_KEY')
[IO.File]::WriteAllLines($envPath, @($values.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }), [Text.UTF8Encoding]::new($false))

$keyValue = $null
$input.Text = ""
[System.Windows.Forms.MessageBox]::Show("Saved successfully. Restart the local website to apply the planning configuration.", "Configuration saved", "OK", "Information") | Out-Null
