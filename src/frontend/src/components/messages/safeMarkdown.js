import DOMPurify from 'dompurify'

// Model output and saved conversations share this final HTML boundary.
export function sanitizeMarkdownHtml(html) {
    return DOMPurify.sanitize(html, {
        ALLOWED_TAGS: ['p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li', 'em', 'strong', 'del', 'blockquote', 'pre', 'code',
            'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'a'],
        ALLOWED_ATTR: ['href', 'title', 'align', 'start', 'colspan', 'rowspan'],
        ALLOW_DATA_ATTR: false,
        ALLOW_ARIA_ATTR: false,
    })
}
