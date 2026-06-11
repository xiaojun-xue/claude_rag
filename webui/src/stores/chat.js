import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const sessions = ref(loadSessions())
  const currentId = ref(sessions.value[0]?.id || null)
  const loading = ref(false)

  // ── Auth state ────────────────────────────────────────────────────────
  const apiKey = ref(localStorage.getItem('rag_api_key') || '')
  const authRequired = ref(false)

  function authHeaders() {
    return apiKey.value ? { 'x-api-key': apiKey.value } : {}
  }

  async function fetchWithAuth(url, options = {}) {
    const headers = { ...(options.headers || {}), ...authHeaders() }
    const resp = await fetch(url, { ...options, headers })
    if (resp.status === 401) authRequired.value = true
    return resp
  }

  function setApiKey(key) {
    apiKey.value = (key || '').trim()
    try { localStorage.setItem('rag_api_key', apiKey.value) } catch (_) {}
    if (apiKey.value) authRequired.value = false
  }

  function clearApiKey() {
    apiKey.value = ''
    try { localStorage.removeItem('rag_api_key') } catch (_) {}
  }

  // ── Token control ─────────────────────────────────────────────────────
  const maxTokens = ref(Number(localStorage.getItem('rag_max_tokens')) || 0)

  function setMaxTokens(val) {
    const n = Number(val)
    maxTokens.value = Number.isFinite(n) && n > 0 ? Math.floor(n) : 0
    try { localStorage.setItem('rag_max_tokens', String(maxTokens.value)) } catch (_) {}
  }

  const current = computed(() => sessions.value.find(s => s.id === currentId.value))

  function newSession() {
    const id = Date.now().toString()
    sessions.value.unshift({ id, title: '新建对话', messages: [], createdAt: Date.now() })
    currentId.value = id
    persist()
  }

  function switchSession(id) {
    currentId.value = id
  }

  function addMessage(role, content, results = null) {
    if (!current.value) newSession()
    const msg = { role, content, results, ts: Date.now() }
    current.value.messages.push(msg)
    if (role === 'user' && current.value.messages.filter(m => m.role === 'user').length === 1) {
      current.value.title = content.slice(0, 20) + (content.length > 20 ? '…' : '')
    }
    persist()
    // Return the reactive proxy (not the raw object) so mutations trigger re-renders
    return current.value.messages[current.value.messages.length - 1]
  }

  async function search(query, mode) {
    addMessage('user', query)
    loading.value = true
    try {
      const endpoint = mode === 'exact' ? '/api/search/exact' : '/api/search'
      const body = mode === 'exact'
        ? { query, top_k: 10 }
        : { query, mode: 'all', top_k: 5 }
      const r = await fetchWithAuth(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const results = await r.json()
      if (results.error) {
        addMessage('assistant', `错误：${results.error}`)
      } else if (!Array.isArray(results) || !results.length) {
        addMessage('assistant', '未找到相关内容，请尝试更换关键词。')
      } else {
        addMessage('assistant', '', results)
      }
    } catch (e) {
      addMessage('assistant', `请求失败：${e.message}`)
    } finally {
      loading.value = false
    }
  }

  async function answer(query) {
    // Collect prior turns BEFORE adding the new messages
    const prevMsgs = current.value?.messages || []
    const history = []
    for (const m of prevMsgs.slice(-6)) {
      if (m.role === 'user' && m.content)
        history.push({ role: 'user', content: m.content })
      else if (m.role === 'assistant' && m.llmAnswer)
        history.push({ role: 'assistant', content: m.llmAnswer })
    }

    addMessage('user', query)
    loading.value = true

    const msg = addMessage('assistant', '', null)
    msg.isStreaming = true
    msg.llmAnswer = ''
    msg.results = null
    persist()

    try {
      const reqBody = { query, history }
      if (maxTokens.value > 0) reqBody.max_tokens = maxTokens.value

      const resp = await fetchWithAuth('/api/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reqBody),
      })

      if (!resp.ok) {
        msg.content = `请求失败：HTTP ${resp.status}`
        msg.isStreaming = false
        loading.value = false
        return
      }

      const reader = resp.body.getReader()
      const dec = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf('\n')) !== -1) {
          const line = buf.slice(0, idx)
          buf = buf.slice(idx + 1)
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === 'results') {
              msg.results = event.data
            } else if (event.type === 'delta') {
              msg.llmAnswer += event.text
            } else if (event.type === 'done') {
              msg.isStreaming = false
              loading.value = false
            } else if (event.type === 'error') {
              msg.content = event.message || '未知错误'
              msg.isStreaming = false
              loading.value = false
            }
          } catch (_) {}
        }
      }
    } catch (e) {
      msg.content = `请求失败：${e.message}`
    } finally {
      msg.isStreaming = false
      loading.value = false
      persist()
    }
  }

  function deleteSession(id) {
    sessions.value = sessions.value.filter(s => s.id !== id)
    if (currentId.value === id) currentId.value = sessions.value[0]?.id || null
    persist()
  }

  function persist() {
    try {
      localStorage.setItem('rag_sessions', JSON.stringify(sessions.value.slice(0, 50)))
    } catch (_) {}
  }

  if (sessions.value.length === 0) newSession()

  return {
    sessions, currentId, current, loading,
    newSession, switchSession, addMessage, search, answer, deleteSession,
    // auth
    apiKey, authRequired, authHeaders, fetchWithAuth, setApiKey, clearApiKey,
    // token control
    maxTokens, setMaxTokens,
  }
})

function loadSessions() {
  try { return JSON.parse(localStorage.getItem('rag_sessions') || '[]') }
  catch (_) { return [] }
}
