<template>
  <section class="page" data-module="firefacility">
    <header class="page-head">
      <div>
        <h2>机坪消防设施管理</h2>
        <p class="page-desc">维护灭火器材台账，按 待检查 → 检查中 → 合格 顺线流转，超期未换流转待更换，换新后回到合格并留下新的检查周期。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">登记灭火器材</button>
        <button class="btn" type="button" @click="exportRows">导出当班检查清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>器材编号</span>
        <input v-model="keyword" placeholder="按器材编号检索" />
      </label>
      <label class="filter-item">
        <span>器材状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>当班检查人</span>
        <input v-model="inspector" placeholder="每一步都要记下检查人" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <form v-if="showCreate" class="filter-bar" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="createForm[field]" :placeholder="`填写${field}`" />
      </label>
      <button class="btn primary" type="submit">提交登记</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>检查记录</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="String(row.id)">
          <tr>
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td>
              <button class="link" type="button" @click="toggleLogs(row)">
                检查记录（{{ logsOf(row).length }}）
              </button>
            </td>
            <td class="row-actions">
              <button
                v-for="action in actionsFor(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
              <span v-if="!actionsFor(row).length">—</span>
            </td>
          </tr>
          <tr v-if="expandedId === row.id">
            <td :colspan="columns.length + 2">
              <ol v-if="logsOf(row).length">
                <li v-for="(log, index) in logsOf(row)" :key="index">
                  {{ log.时间 }} · {{ log.动作 }} · {{ log.原状态 }} → {{ log.新状态 }} · 检查人：{{ log.检查人 }} · 检查单号：{{ log.检查单号 || '—' }}
                </li>
              </ol>
              <span v-else class="empty-state">暂无检查记录</span>
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无灭火器材数据，可先登记灭火器材</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条灭火器材台账</span>
      <span v-if="noticeMessage">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type InspectionLog = {
  时间: string
  动作: string
  原状态: string
  新状态: string
  检查人: string
  检查单号: string
}

type Row = {
  id: number
  status?: string
  检查记录?: InspectionLog[]
  [key: string]: unknown
}

const ENDPOINT = '/api/firefacility'
const columns = ["器材编号", "器材类型", "归属区域", "存放位置", "检查人", "检查时间", "下次检查日期", "器材状态"]
const statuses = ["待检查", "检查中", "待更换", "合格"]
const createFields = ["器材编号", "器材类型", "归属区域", "存放位置", "下次检查日期"]
// 每个状态允许执行的动作：只能顺线走，页面上也不给出跳级入口
const ACTION_FLOW: Record<string, string[]> = {
  '待检查': ['开始检查', '标记超期'],
  '检查中': ['检查合格', '标记超期'],
  '待更换': ['完成换新'],
  '合格': [],
}

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<{ label: string; value: number }[]>([])
const errorMessage = ref('')
const noticeMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const inspector = ref(session.operator)
const expandedId = ref<number | null>(null)
const showCreate = ref(false)
const createForm = ref<Record<string, string>>(Object.fromEntries(createFields.map((field) => [field, ''])))
// 同一具器材同一次检查共用一个检查单号：重试/重复点击都带上它，后端只生效第一次
const tickets = new Map<string, string>()

function actionsFor(row: Row): string[] {
  return ACTION_FLOW[String(row.status ?? '')] ?? []
}

function logsOf(row: Row): InspectionLog[] {
  return Array.isArray(row.检查记录) ? row.检查记录 as InspectionLog[] : []
}

function toggleLogs(row: Row) {
  expandedId.value = expandedId.value === row.id ? null : row.id
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  return params.toString()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  const query = buildQuery()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  const key = `${row.id}:${action}`
  let ticket = tickets.get(key)
  if (!ticket) {
    ticket = `INSP-${row.id}-${Date.now()}`
    tickets.set(key, ticket)
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, 检查人: inspector.value.trim(), 检查单号: ticket } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '动作未生效，请稍后重试')
    }
    tickets.delete(key)
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '灭火器材操作失败'
  }
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '登记失败，请检查必填字段')
    }
    showCreate.value = false
    createForm.value = Object.fromEntries(createFields.map((field) => [field, '']))
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '灭火器材登记失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const [listPayload, statsPayload] = await Promise.all([
      fetchJson<{ items: Row[]; total: number }>(`${ENDPOINT}${query ? `?${query}` : ''}`),
      fetchJson<{ total: number; counts: Record<string, number> }>(`${ENDPOINT}/stats`),
    ])
    rows.value = listPayload.items ?? []
    total.value = listPayload.total ?? rows.value.length
    stats.value = statuses.map((status) => ({ label: `${status}器材`, value: statsPayload.counts?.[status] ?? 0 }))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '设施台账读取失败'
  }
}

onMounted(reload)
</script>
