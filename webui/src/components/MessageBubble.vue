<template>
  <div class="bubble-wrap" :class="msg.role">
    <div v-if="msg.role === 'assistant'" class="avatar">🤖</div>
    <div class="bubble">
      <template v-if="msg.role === 'assistant'">

        <!-- LLM streaming answer -->
        <div v-if="msg.llmAnswer || msg.isStreaming" class="llm-answer">
          <div class="llm-label">
            ✨ AI 回答
            <button
              v-if="msg.llmAnswer && !msg.isStreaming"
              class="copy-btn"
              @click="copyAnswer"
            >{{ copiedAnswer ? '已复制 ✓' : '复制' }}</button>
          </div>
          <div
            class="llm-text md"
            v-html="renderedAnswer"
            @click="handleClick"
          />
          <span v-if="msg.isStreaming" class="cursor">▋</span>
        </div>

        <!-- Divider -->
        <div v-if="(msg.llmAnswer || msg.isStreaming) && msg.results" class="divider">
          参考来源
        </div>

        <!-- Chunk results -->
        <SearchResult
          v-if="msg.results"
          :results="msg.results"
          @view-file="$emit('view-file', $event)"
        />

        <!-- Plain text (errors / pure search) -->
        <div v-else-if="!msg.llmAnswer && !msg.isStreaming && msg.content" class="text">
          {{ msg.content }}
        </div>

      </template>
      <div v-else class="text">{{ msg.content }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import SearchResult from './SearchResult.vue'

marked.use({ gfm: true, breaks: true })

const props = defineProps({ msg: Object })
const emit = defineEmits(['view-file'])

const copiedAnswer = ref(false)

// Doc names available in current results (for citation linking)
const docNames = computed(() =>
  [...new Set((props.msg.results || []).map(r => r.doc_name).filter(Boolean))]
)

const renderedAnswer = computed(() => {
  const text = props.msg.llmAnswer || ''
  if (!text) return ''
  let html
  try { html = marked.parse(text) } catch { html = text }
  html = DOMPurify.sanitize(html)
  // Make [文件名] references clickable when they match a known doc name
  for (const name of docNames.value) {
    const safe = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    html = html.replace(
      new RegExp(`\\[${safe}\\](?!\\()`, 'g'),
      `<span class="citation" data-doc="${name}" title="查看文件">[${name}]</span>`
    )
  }
  return html
})

async function copyAnswer() {
  const text = props.msg.llmAnswer || ''
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // Fallback for http (non-secure) contexts
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
  }
  copiedAnswer.value = true
  setTimeout(() => { copiedAnswer.value = false }, 2000)
}

function handleClick(e) {
  // Citation click → open file drawer
  const cite = e.target.closest('.citation')
  if (cite) emit('view-file', cite.dataset.doc)
  // Copy button inside code block
  const copyBtn = e.target.closest('.code-copy')
  if (copyBtn) {
    const pre = copyBtn.closest('pre')
    const code = pre?.querySelector('code')?.innerText || ''
    navigator.clipboard.writeText(code).catch(() => {})
    copyBtn.textContent = '已复制 ✓'
    setTimeout(() => { copyBtn.textContent = '复制' }, 2000)
  }
}
</script>

<style scoped>
.bubble-wrap {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 6px 20px;
}
.bubble-wrap.user { flex-direction: row-reverse; }

.avatar { font-size: 22px; flex-shrink: 0; margin-top: 2px; }

.bubble {
  max-width: 76%;
  padding: 10px 14px;
  border-radius: 12px;
  line-height: 1.6;
  font-size: 14px;
}
.user .bubble {
  background: #3b82f6;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.assistant .bubble {
  background: #f0f2f5;
  color: #1a1a1a;
  border-bottom-left-radius: 4px;
  max-width: 88%;
}

.text { white-space: pre-wrap; word-break: break-word; }

/* ── LLM answer header ─── */
.llm-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #7c3aed;
  margin-bottom: 8px;
}
.copy-btn {
  margin-left: auto;
  background: none;
  border: 1px solid #c4b5fd;
  color: #7c3aed;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s;
}
.copy-btn:hover { background: #ede9fe; }

/* ── Streaming cursor ─── */
.cursor {
  display: inline-block;
  animation: blink 1s step-end infinite;
  color: #7c3aed;
  font-size: 15px;
}
@keyframes blink { 50% { opacity: 0; } }

/* ── Sources divider ─── */
.divider {
  font-size: 12px;
  color: #888;
  margin: 12px 0 6px;
  padding-top: 10px;
  border-top: 1px solid #e4e6ea;
  font-weight: 500;
}

/* ── Markdown body ─── */
.md { line-height: 1.75; word-break: break-word; }

.md :deep(h1), .md :deep(h2), .md :deep(h3) {
  font-weight: 700; margin: 1em 0 0.4em; line-height: 1.3;
}
.md :deep(h1) { font-size: 1.3em; }
.md :deep(h2) { font-size: 1.15em; }
.md :deep(h3) { font-size: 1.05em; }

.md :deep(p) { margin: 0.5em 0; }

.md :deep(ul), .md :deep(ol) {
  margin: 0.4em 0; padding-left: 1.4em;
}
.md :deep(li) { margin: 0.2em 0; }

.md :deep(code) {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.88em;
  background: #e8eaf0;
  padding: 1px 5px;
  border-radius: 3px;
}

.md :deep(pre) {
  position: relative;
  background: #f6f8fa;
  border: 1px solid #e4e6ea;
  border-radius: 6px;
  padding: 12px 14px;
  margin: 0.6em 0;
  overflow-x: auto;
}
.md :deep(pre code) {
  background: none;
  padding: 0;
  font-size: 12px;
  line-height: 1.55;
}

.md :deep(blockquote) {
  border-left: 3px solid #c4b5fd;
  margin: 0.6em 0;
  padding: 4px 12px;
  color: #555;
  background: #faf5ff;
  border-radius: 0 4px 4px 0;
}

.md :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.6em 0;
  font-size: 13px;
}
.md :deep(th), .md :deep(td) {
  border: 1px solid #e4e6ea;
  padding: 5px 10px;
  text-align: left;
}
.md :deep(th) { background: #f0f2f5; font-weight: 600; }

.md :deep(a) { color: #3b82f6; text-decoration: none; }
.md :deep(a:hover) { text-decoration: underline; }

.md :deep(hr) { border: none; border-top: 1px solid #e4e6ea; margin: 0.8em 0; }

/* ── Citations ─── */
.md :deep(.citation) {
  color: #7c3aed;
  background: #ede9fe;
  border-radius: 3px;
  padding: 0 4px;
  cursor: pointer;
  font-size: 0.9em;
  transition: background 0.15s;
}
.md :deep(.citation:hover) { background: #ddd6fe; }
</style>
