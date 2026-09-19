$ErrorActionPreference = 'Stop'
$out = 'C:\Users\seele\Desktop\test\submission\qa_template'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $items = @(
        @{ Name = 'template'; Path = 'C:\Users\seele\Desktop\test\submission\template_reference.docx' },
        @{ Name = 'system'; Path = 'C:\Users\seele\Desktop\test\submission\2026-chongqing-ai-competition\01-系统设计文档-完整版.docx' }
    )
    foreach ($item in $items) {
        $pdf = Join-Path $out ($item.Name + '.pdf')
        if (Test-Path -LiteralPath $pdf) { Remove-Item -LiteralPath $pdf -Force }
        $doc = $word.Documents.Open($item.Path, $false, $true)
        try { $doc.ExportAsFixedFormat($pdf, 17) } finally { $doc.Close($false) }
        Write-Output $pdf
    }
}
finally { $word.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null }
