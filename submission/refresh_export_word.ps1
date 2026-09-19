$ErrorActionPreference = 'Stop'
$out = 'C:\Users\seele\Desktop\test\submission\2026-chongqing-ai-competition'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

try {
    Get-ChildItem -LiteralPath $out -Filter '*完整版.docx' | Sort-Object Name | ForEach-Object {
        $docx = $_.FullName
        $pdf = [System.IO.Path]::ChangeExtension($docx, '.pdf')
        $doc = $null
        try {
            $doc = $word.Documents.Open($docx, $false, $false)
            $doc.Repaginate()
            foreach ($toc in $doc.TablesOfContents) {
                $toc.Update()
            }
            $doc.Fields.Update() | Out-Null
            $doc.Save()
            if (Test-Path -LiteralPath $pdf) {
                Remove-Item -LiteralPath $pdf -Force
            }
            $doc.ExportAsFixedFormat($pdf, 17)
            Write-Output ("exported " + $_.Name + " -> " + [System.IO.Path]::GetFileName($pdf))
        }
        finally {
            if ($null -ne $doc) {
                $doc.Close($false)
                [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($doc)
            }
        }
    }
}
finally {
    $word.Quit()
    [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
}
