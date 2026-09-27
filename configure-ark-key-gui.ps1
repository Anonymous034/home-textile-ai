$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectRoot "backend\.env"

$form = New-Object System.Windows.Forms.Form
$form.Text = "Configure Volcengine Agent Plan API Key"
$form.ClientSize = New-Object System.Drawing.Size(520, 210)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(15, 18, 28)
$form.ForeColor = [System.Drawing.Color]::White

$title = New-Object System.Windows.Forms.Label
$title.Text = "Enter a new Agent Plan API Key not shared in chat"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 12, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(24, 22)
$title.Size = New-Object System.Drawing.Size(470, 30)
$form.Controls.Add($title)

$tip = New-Object System.Windows.Forms.Label
$tip.Text = "Saved locally to backend/.env. The key is masked while typing."
$tip.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$tip.ForeColor = [System.Drawing.Color]::FromArgb(145, 165, 185)
$tip.Location = New-Object System.Drawing.Point(24, 58)
$tip.Size = New-Object System.Drawing.Size(470, 24)
$form.Controls.Add($tip)

$input = New-Object System.Windows.Forms.TextBox
$input.Location = New-Object System.Drawing.Point(24, 91)
$input.Size = New-Object System.Drawing.Size(470, 30)
$input.Font = New-Object System.Drawing.Font("Consolas", 11)
$input.UseSystemPasswordChar = $true
$input.BackColor = [System.Drawing.Color]::FromArgb(5, 9, 16)
$input.ForeColor = [System.Drawing.Color]::White
$form.Controls.Add($input)

$save = New-Object System.Windows.Forms.Button
$save.Text = "Save securely"
$save.Location = New-Object System.Drawing.Point(280, 145)
$save.Size = New-Object System.Drawing.Size(102, 38)
$save.BackColor = [System.Drawing.Color]::FromArgb(0, 185, 210)
$save.FlatStyle = "Flat"
$save.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $save
$form.Controls.Add($save)

$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = "Cancel"
$cancel.Location = New-Object System.Drawing.Point(392, 145)
$cancel.Size = New-Object System.Drawing.Size(102, 38)
$cancel.FlatStyle = "Flat"
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.CancelButton = $cancel
$form.Controls.Add($cancel)

$input.Focus()
$result = $form.ShowDialog()
if ($result -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }

$apiKey = $input.Text.Trim()
if ($apiKey.Length -lt 20 -or $apiKey -match "\s") {
  [System.Windows.Forms.MessageBox]::Show(
    "Invalid key. Paste the exact value copied from Ark API Key Management.",
    "Unable to save",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Warning
  ) | Out-Null
  exit 1
}

$values = [ordered]@{}
if (Test-Path -LiteralPath $envPath) {
  foreach ($line in Get-Content -LiteralPath $envPath -Encoding utf8) {
    if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') { $values[$matches[1]] = $matches[2] }
  }
}
$values['ARK_API_KEY'] = $apiKey
$values['ARK_IMAGE_MODEL'] = 'doubao-seedream-5.0-lite'
$values['ARK_IMAGE_ENDPOINT'] = 'https://ark.cn-beijing.volces.com/api/plan/v3/images/generations'
$values['FRONTEND_ORIGIN'] = 'http://localhost:3000'
[IO.File]::WriteAllLines($envPath, @($values.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }), [Text.UTF8Encoding]::new($false))
$apiKey = $null
$input.Text = ""

[System.Windows.Forms.MessageBox]::Show(
  "Saved successfully. Return to Codex to continue the generation test.",
  "Configuration saved",
  [System.Windows.Forms.MessageBoxButtons]::OK,
  [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null
