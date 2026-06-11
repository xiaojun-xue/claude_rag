<template>
  <Teleport to="body">
    <transition name="drawer">
      <div v-if="docName" class="overlay" @click.self="$emit('close')">
        <div class="drawer">
          <div class="drawer-header">
            <span class="drawer-title">{{ docName }}</span>
            <span class="chunk-count" v-if="chunks.length">{{ chunks.length }} chunks</span>
            <button class="close-btn" @click="$emit('close')">✕</button>
          </div>

          <div v-if="loadError" class="error">{{ loadError }}</div>

          <div v-else-if="loading" class="loading-text">加载中...</div>

          <div v-else class="drawer-body" ref="body">
            <div v-for="(c, i) in chunks" :key="i" class="chunk-block">
              <div class="chunk-meta">chunk {{ c.chunk_index + 1 }} / {{ c.total_chunks }}</div>
              <pre v-html="highlighted(c.content, c.file_type)" class="code-block" />
            </div>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useChatStore } from '../stores/chat'
import hljs from 'highlight.js/lib/core'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import shell from 'highlight.js/lib/languages/shell'
import ini from 'highlight.js/lib/languages/ini'
import 'highlight.js/styles/github.css'

hljs.registerLanguage('c', c)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('h', c)
hljs.registerLanguage('py', python)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('go', go)
hljs.registerLanguage('rs', rust)
hljs.registerLanguage('sh', shell)
hljs.registerLanguage('ini', ini)

const props = defineProps({ docName: String })
defineEmits(['close'])

const store = useChatStore()

const chunks = ref([])
const loading = ref(false)
const loadError = ref('')

const EXT_MAP = { c:'c', h:'h', cpp:'cpp', cc:'cpp', py:'py', js:'js', ts:'ts', go:'go', rs:'rs', sh:'sh', ini:'ini' }

function highlighted(code, fileType) {
  const lang = EXT_MAP[fileType]
  if (lang && hljs.getLanguage(lang)) {
    return hljs.highlight(code, { language: lang }).value
  }
  return hljs.highlightAuto(code).value
}

watch(() => props.docName, async (name) => {
  if (!name) { chunks.value = []; return }
  loading.value = true
  loadError.value = ''
  chunks.value = []
  try {
    const r = await store.fetchWithAuth(`/api/file/${encodeURIComponent(name)}`)
    const data = await r.json()
    if (data.error) loadError.value = data.error
    else chunks.value = data
  } catch (e) {
    loadError.value = `加载失败：${e.message}`
  } finally {
    loading.value = false
  }
}, { immediate: true })
</script>

<style scoped>
.overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.3);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: 55%;
  min-width: 400px;
  max-width: 900px;
  background: #fff;
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 20px rgba(0,0,0,0.15);
  overflow: hidden;
}

.drawer-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid #e4e6ea;
  background: #f7f8fa;
}

.drawer-title {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunk-count { font-size: 12px; color: #888; }

.close-btn {
  background: none; border: none;
  font-size: 18px; color: #666;
  cursor: pointer; padding: 0 4px;
  line-height: 1;
}
.close-btn:hover { color: #333; }

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chunk-block { display: flex; flex-direction: column; gap: 4px; }

.chunk-meta {
  font-size: 11px; color: #aaa;
  border-top: 1px solid #f0f0f0;
  padding-top: 4px;
}
.chunk-block:first-child .chunk-meta { border-top: none; }

.code-block {
  margin: 0;
  padding: 12px 14px;
  background: #f6f8fa;
  border: 1px solid #e4e6ea;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'Consolas', 'Monaco', 'Menlo', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.55;
  overflow-x: auto;
}

.loading-text, .error {
  padding: 30px; text-align: center;
  color: #888; font-size: 14px;
}
.error { color: #e55; }

.drawer-enter-active, .drawer-leave-active { transition: transform 0.25s ease; }
.drawer-enter-from, .drawer-leave-to { transform: translateX(100%); }
</style>
