// Formatting is shared by search, cell details, and export. Never truncate source data.
export const resultValueText = value => {
    if (value == null) return ''
    return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

export const resultColumnKeys = rows => [...new Set(rows.flatMap(row => Object.keys(row)))]

export const resultRowsCsv = (rows, headers) => {
    const quote = text => `"${text.replace(/"/g, '""')}"`
    const cell = value => {
        let text = resultValueText(value)
        // Keep user-controlled text from becoming a spreadsheet formula.
        if (typeof value === 'string' && /^[\s]*[=+@-]/.test(text)) text = `'${text}`
        return quote(text)
    }
    return [
        headers.map(header => cell(header.title)).join(','),
        ...rows.map(row => headers.map(header => cell(row[header.key])).join(',')),
    ].join('\r\n')
}
