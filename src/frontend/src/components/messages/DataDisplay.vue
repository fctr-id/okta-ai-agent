<template>
    <div class="data-display">
        <!-- Stream Data Table -->
        <v-data-table
            v-if="isStreamData"
            :headers="headers"
            :items="items"
            :loading="loading"
            class="mt-2"
        />

        <!-- JSON Display -->
        <div v-else-if="isJsonData" class="json-content">
            <pre>{{ formattedJson }}</pre>
        </div>

        <!-- Simple Error Display -->
        <div v-else-if="isError" class="error-content">
            {{ typeof content === 'string' ? content : content.message }}
        </div>

        <!-- Fallback Display -->
        <div v-else class="text-content">
            {{ content }}
        </div>
    </div>
</template>

<script setup>
import { computed } from 'vue'
import { MessageType } from './messageTypes'

const props = defineProps({
    type: String,
    content: {
        type: [Array, Object, String], // Added String type
        required: true
    },
    metadata: {
        type: Object,
        default: () => ({})
    },
    loading: {
        type: Boolean,
        default: false
    }
})

const isStreamData = computed(() => props.type === MessageType.STREAM)
const isJsonData = computed(() => props.type === MessageType.JSON)
const isError = computed(() => props.type === MessageType.ERROR)

const headers = computed(() => props.metadata?.headers || [])
const items = computed(() => Array.isArray(props.content) ? props.content : [])
const formattedJson = computed(() => 
    JSON.stringify(props.content, null, 2)
)
</script>

<style scoped>
.data-display {
    width: 100%;
    margin: 8px 0;
}

.json-content {
    background: #f5f5f5;
    padding: 12px;
    border-radius: 4px;
    overflow-x: auto;
}

.json-content pre {
    margin: 0;
    font-family: monospace;
    font-size: 14px;
    white-space: pre-wrap;
    word-break: break-word;
}

.error-content {
    color: #DC2626;
    background-color: #FEF2F2;
    border: 0px solid #FCA5A5;
    padding: 0px;
    border-radius: 4px;
}
</style>