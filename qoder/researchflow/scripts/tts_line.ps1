param(
  [Parameter(Mandatory = $true)][string]$TextFile,
  [Parameter(Mandatory = $true)][string]$OutWav,
  [string]$Voice = 'Microsoft Huihui Desktop',
  [int]$Rate = 8
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice($Voice)
$synth.Rate = $Rate
$synth.SetOutputToWaveFile($OutWav)
# Read explicit UTF-8 so the CJK narration survives PowerShell 5.1's default encoding.
$text = [System.IO.File]::ReadAllText($TextFile, (New-Object System.Text.UTF8Encoding($false)))
$synth.Speak($text)
$synth.SetOutputToNull()
$synth.Dispose()
