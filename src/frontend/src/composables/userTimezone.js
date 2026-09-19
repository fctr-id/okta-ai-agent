export const getBrowserTimezone = () => {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
    } catch {
        return undefined
    }
}
