import { Tooltip } from 'vuetify/directives'

let nextHintId = 0
const hintIds = new WeakMap()

function withHintId(el, binding) {
  // Vuetify mounts directive tooltips as separate Vue roots. Give each one
  // a stable ID so aria-describedby never points at another control's hint.
  if (!hintIds.has(el)) hintIds.set(el, `tako-hint-${++nextHintId}`)
  const value = binding.value && typeof binding.value === 'object'
    ? binding.value
    : { text: binding.value }
  return { ...binding, value: { ...value, id: hintIds.get(el) } }
}

export const Hint = {
  mounted(el, binding, vnode, previousVnode) {
    Tooltip.mounted(el, withHintId(el, binding), vnode, previousVnode)
  },
  updated(el, binding, vnode, previousVnode) {
    Tooltip.updated(el, withHintId(el, binding), vnode, previousVnode)
  },
  unmounted(el) {
    Tooltip.unmounted(el)
    hintIds.delete(el)
  }
}
