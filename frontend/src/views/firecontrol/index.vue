<template>
  <section class="page" data-module="firecontrol">
    <header class="page-head">
      <div>
        <h2>机坪消防设施管理</h2>
        <p class="page-desc">
          灭火器材检查状态流转：待检查 → 检查中 → 合格；超期未换流转到待更换，换新后回到合格并开启新检查周期。
          每一步记录检查人与时间，不允许跳级，同一批次重复提交只生效第一次。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记灭火器材</button>
        <button class="btn" type="button" @click="exportRows">导出当班检查清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>器材编号</span>
        <input v-model="filters.keyword" placeholder="按器材编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>归属区域</span>
        <input v-model="filters.area" placeholder="按归属区域检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actionsFor(row)"
              :key="action.name"
              class="link"
              type="button"
              @click="openAction(action, row)"
            >
              {{ action.name }}
            </button>
            <span v-if="!actionsFor(row).length" class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无消防设施数据，可先登记灭火器材</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 具灭火器材（页面台账口径）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="records-block">
      <h3>检查明细（每一步的检查人与时间）</h3>
      <form class="filter-bar" @submit.prevent="reloadRecords">
        <label class="filter-item">
          <span>器材编号</span>
          <input v-model="recordFilters.keyword" placeholder="按器材编号检索" />
        </label>
        <label class="filter-item">
          <span>归属区域</span>
          <input v-model="recordFilters.area" placeholder="按归属区域检索" />
        </label>
        <label class="filter-item">
          <span>检查日期</span>
          <input v-model="recordFilters.day" type="date" />
        </label>
        <button class="btn" type="submit">查询明细</button>
        <button class="btn ghost" type="button" @click="resetRecordFilters">重置</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in recordColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rec in records" :key="String(rec.id)">
            <td v-for="column in recordColumns" :key="column">{{ rec[column] || '—' }}</td>
          </tr>
          <tr v-if="!records.length">
            <td :colspan="recordColumns.length" class="empty-state">暂无检查明细</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>共 {{ recordTotal }} 条检查明细</span></footer>
    </section>

    <!-- 动作弹窗：录入检查人；提交到期未换需填到期原因 -->
    <div v-if="dialog.action" class="modal-mask" @click.self="closeDialog">
      <div class="modal-card">
        <h3>{{ dialog.action.name }} · {{ dialog.row?.['器材编号'] }}</h3>
        <p class="muted-text">当前状态：{{ dialog.row?.status }} · 归属区域：{{ dialog.row?.['归属区域'] }}</p>
        <label class="form-item">
          <span>检查人 / 更换人 *</span>
          <input v-model="dialog.form.检查人" placeholder="结束检查必须填写检查人" />
        </label>
        <label v-if="dialog.action.name === '提交到期未换'" class="form-item">
          <span>到期原因 *</span>
          <textarea v-model="dialog.form.到期原因" rows="3" placeholder="如：压力不足、检查周期超期未换"></textarea>
        </label>
        <label v-else-if="dialog.action.name === '完成换新'" class="form-item">
          <span>换新备注</span>
          <input v-model="dialog.form.检查结果" placeholder="默认：换新后合格" />
        </label>
        <label v-else-if="dialog.action.name === '提交合格'" class="form-item">
          <span>检查结果</span>
          <input v-model="dialog.form.检查结果" placeholder="默认：合格" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAction">
            {{ submitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
        <p v-if="dialog.error" class="error-text">{{ dialog.error }}</p>
      </div>
    </div>

    <!-- 登记弹窗 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal-card">
        <h3>登记灭火器材</h3>
        <label v-for="field in createFields" :key="field.key" class="form-item">
          <span>{{ field.label }}<i v-if="field.required">*</i></span>
          <input v-model="createForm[field.key]" :placeholder="`请输入${field.label}`" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">确认登记</button>
        </div>
        <p v-if="createError" class="error-text">{{ createError }}</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Stats = Record<string, number>

const ENDPOINT = '/api/firecontrol'
const columns = [
  '器材编号', '器材类型', '规格型号', '归属区域', '存放位置', '检查批次',
  'status', '检查人', '检查时间', '检查结果', '上次检查日', '下次检查日',
  '到期原因', '更换人', '更换时间',
]
const recordColumns = ['器材编号', '归属区域', '检查批次', '动作', '检查人', '时间', '检查结果', '到期原因']
const statuses = ['待检查', '检查中', '合格', '待更换']

// 状态只能顺向流转：不同状态只给出合法的下一步动作，避免在页面上跳级
const ACTIONS_BY_STATUS: Record<string, { name: string; next: string }[]> = {
  待检查: [{ name: '开始检查', next: '检查中' }],
  检查中: [
    { name: '提交合格', next: '合格' },
    { name: '提交到期未换', next: '待更换' },
  ],
  合格: [],
  待更换: [{ name: '完成换新', next: '合格' }],
}

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stats>({ 待检查: 0, 检查中: 0, 合格: 0, 待更换: 0, 器材总数: 0 })
const records = ref<Row[]>([])
const recordTotal = ref(0)
const errorMessage = ref('')
const submitting = ref(false)

const filters = reactive({ keyword: '', status: '', area: '' })
const recordFilters = reactive({ keyword: '', area: '', day: '' })

const statCards = computed(() => [
  { label: '待检查', value: stats.value['待检查'] ?? 0 },
  { label: '检查中', value: stats.value['检查中'] ?? 0 },
  { label: '合格', value: stats.value['合格'] ?? 0 },
  { label: '待更换', value: stats.value['待更换'] ?? 0 },
  { label: '器材总数', value: stats.value['器材总数'] ?? 0 },
])

function actionsFor(row: Row) {
  return ACTIONS_BY_STATUS[String(row.status ?? '')] ?? []
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.area = ''
  void reload()
}

function resetRecordFilters() {
  recordFilters.keyword = ''
  recordFilters.area = ''
  recordFilters.day = ''
  void reloadRecords()
}

// 导出当班检查清单：带上与页面完全相同的筛选条件，清单条数即页面 total
function exportRows() {
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.area) query.set('area', filters.area)
  const qs = query.toString()
  window.open(`${ENDPOINT}/export${qs ? `?${qs}` : ''}`, '_blank')
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.area) query.set('area', filters.area)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('消防设施台账读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (payload.stats) stats.value = payload.stats
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防设施台账读取失败'
  }
}

async function reloadRecords() {
  const query = new URLSearchParams()
  if (recordFilters.keyword) query.set('keyword', recordFilters.keyword)
  if (recordFilters.area) query.set('area', recordFilters.area)
  if (recordFilters.day) query.set('day', recordFilters.day)
  try {
    const response = await request(`${ENDPOINT}/records?${query.toString()}`)
    if (!response.ok) throw new Error('检查明细读取失败')
    const payload = await response.json()
    records.value = payload.items ?? []
    recordTotal.value = payload.total ?? records.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查明细读取失败'
  }
}

// ---------- 动作弹窗 ----------
const dialog = reactive<{
  action: { name: string; next: string } | null
  row: Row | null
  form: { 检查人: string; 检查结果: string; 到期原因: string }
  error: string
}>({
  action: null,
  row: null,
  form: { 检查人: '', 检查结果: '', 到期原因: '' },
  error: '',
})

function openAction(action: { name: string; next: string }, row: Row) {
  dialog.action = action
  dialog.row = row
  dialog.form = { 检查人: String(row['检查人'] ?? ''), 检查结果: '', 到期原因: '' }
  dialog.error = ''
}

function closeDialog() {
  dialog.action = null
  dialog.row = null
  dialog.error = ''
}

async function submitAction() {
  if (!dialog.action || !dialog.row) return
  dialog.error = ''
  if (!dialog.form.检查人.trim()) {
    dialog.error = '检查人缺失，不允许结束检查/推进状态'
    return
  }
  if (dialog.action.name === '提交到期未换' && !dialog.form.到期原因.trim()) {
    dialog.error = '请填写到期原因后再流转到待更换'
    return
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${dialog.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: dialog.action.name, ...dialog.form } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '动作未生效，请稍后重试')
    }
    closeDialog()
    await Promise.all([reload(), reloadRecords()])
  } catch (error) {
    dialog.error = error instanceof Error ? error.message : '动作执行失败'
  } finally {
    submitting.value = false
  }
}

// ---------- 登记弹窗 ----------
const createFields = [
  { key: '器材编号', label: '器材编号', required: true },
  { key: '器材类型', label: '器材类型', required: true },
  { key: '规格型号', label: '规格型号', required: false },
  { key: '归属区域', label: '归属区域（跨区域必填）', required: true },
  { key: '存放位置', label: '存放位置', required: true },
  { key: '检查批次', label: '检查批次', required: true },
]
const emptyCreateForm = (): Record<string, string> => ({
  器材编号: '', 器材类型: '', 规格型号: '', 归属区域: '', 存放位置: '', 检查批次: '2026-09 班',
})
const createOpen = ref(false)
const createForm = ref<Record<string, string>>(emptyCreateForm())
const createError = ref('')

function openCreate() {
  createForm.value = emptyCreateForm()
  createError.value = ''
  createOpen.value = true
}

async function submitCreate() {
  createError.value = ''
  const missing = createFields
    .filter((f) => f.required && !String(createForm.value[f.key] ?? '').trim())
    .map((f) => f.label)
  if (missing.length) {
    createError.value = `缺少必填字段：${missing.join('、')}`
    return
  }
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '登记失败')
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void reload()
  void reloadRecords()
})
</script>

<style scoped>
.muted-text { color: var(--muted); font-size: 12px; }
.records-block { margin-top: 24px; }
.records-block h3 { font-size: 15px; margin: 0 0 8px; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 20;
}
.modal-card {
  width: 420px; background: #fff; border-radius: 10px; padding: 18px 20px;
  border: 1px solid var(--border);
}
.modal-card h3 { margin: 0 0 6px; font-size: 16px; }
.form-item { display: block; margin: 10px 0; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item i { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input, .form-item textarea {
  width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; font: inherit;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
</style>
