/** Styles of the printable report. Used on the screen and copied into the downloaded HTML file (which has no script). */
export const REPORT_CSS = `
.report-sheet{box-sizing:border-box;background:#fff;color:#000;max-width:210mm;margin:0 auto;padding:16mm;font-family:Georgia,"Times New Roman",serif;font-size:13px;line-height:1.55;text-align:start}
.report-sheet *{box-sizing:border-box;color:inherit}
.report-sheet h1{font-size:22px;line-height:1.35;margin:0 0 4px;font-weight:700}
.report-sheet h2{font-size:15px;margin:18px 0 6px;padding-bottom:3px;border-bottom:1px solid #000;font-weight:700;break-after:avoid}
.report-sheet h3{font-size:13px;margin:8px 0 2px;font-weight:700}
.report-sheet p{margin:3px 0;color:#000}
.report-sheet ul{margin:2px 0;padding-inline-start:20px}
.report-sheet .rp-meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2px 18px;margin:10px 0;padding:8px 10px;border:1px solid #000}
.report-sheet .rp-meta div{display:flex;gap:6px}
.report-sheet .rp-meta dt{font-weight:700}
.report-sheet .rp-meta dd{margin:0}
.report-sheet dl{margin:0}
.report-sheet .rp-banner{margin:8px 0;padding:6px 10px;border:2px solid #000;font-weight:700;break-inside:avoid}
.report-sheet .rp-note{margin:8px 0;padding:6px 10px;border:1px dashed #000;font-size:12px}
.report-sheet .rp-tag{display:inline-block;margin:0 0 2px;padding:0 6px;border:1px solid #000;font-family:Arial,Helvetica,sans-serif;font-size:10px;letter-spacing:.4px;text-transform:uppercase}
.report-sheet .rp-remedy{margin:10px 0;padding:8px 10px;border:1px solid #000;break-inside:avoid}
.report-sheet .rp-remedy-head{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.report-sheet .rp-source{margin:6px 0;padding:6px 8px;border-inline-start:3px solid #000;break-inside:avoid;font-size:12px}
.report-sheet .rp-excerpt{margin:2px 0;white-space:pre-wrap;font-style:italic;direction:ltr;text-align:left;unicode-bidi:isolate}
.report-sheet .rp-small{font-size:11px}
.report-sheet .rp-foot{margin-top:18px;padding-top:6px;border-top:1px solid #000;font-size:11px}
.report-sheet[dir="rtl"]{font-family:"Jameel Noori Nastaleeq","Noto Nastaliq Urdu",serif;font-size:16px;line-height:2.1}
.report-sheet[dir="rtl"] h1{font-size:24px;line-height:2}
.report-sheet[dir="rtl"] h2{font-size:18px}
.report-sheet[dir="rtl"] h3{font-size:16px}
.report-sheet[dir="rtl"] .rp-tag{font-family:"Jameel Noori Nastaleeq","Noto Nastaliq Urdu",serif;font-size:13px;letter-spacing:0;text-transform:none}
.report-sheet[dir="rtl"] .rp-small,.report-sheet[dir="rtl"] .rp-note,.report-sheet[dir="rtl"] .rp-source{font-size:15px}
.report-sheet .rp-excerpt{font-family:Georgia,"Times New Roman",serif;font-size:12px;line-height:1.5}
`;
