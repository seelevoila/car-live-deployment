$docDir = 'C:\Users\seele\Desktop\test\submission\2026-chongqing-ai-competition'
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $files = Get-ChildItem -LiteralPath $docDir -Filter '*-完整版.docx' | Sort-Object Name
    foreach ($file in $files) {
        $pdfPath = [System.IO.Path]::ChangeExtension($file.FullName, '.pdf')
        if (Test-Path -LiteralPath $pdfPath) {
            Remove-Item -LiteralPath $pdfPath -Force
        }
        $doc = $word.Documents.Open($file.FullName, $false, $true)
        try {
            $doc.ExportAsFixedFormat($pdfPath, 17)
        }
        finally {
            $doc.Close($false)
        }
        Write-Output ("OK " + $file.Name + " -> " + $pdfPath)
    }
}
finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
Get-ChildItem -LiteralPath $docDir -Filter '*-完整版.pdf' | Sort-Object Name | Select-Object Name, Length
