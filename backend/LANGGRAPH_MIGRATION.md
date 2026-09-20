# LangGraph Migration Guide — 0.1.19 → 0.2.x

## Durum: FROZEN (0.1.19)

`requirements.txt`'te `langgraph==0.1.19` olarak sabitlenmiştir.
Bu kılavuz, 0.2.x'e güvenli geçiş için hazırlanmıştır.

---

## 0.1.19 vs 0.2.x API Farkları

### 1. `add_conditional_edges` — BREAKING

```python
# 0.1.19 (mevcut kod — ÇALIŞIYOR)
graph.add_conditional_edges(
    "data_ingestion",
    route_fn,
    {
        "pnl":  "pnl",
        "end":  END,
    },
)

# 0.2.x — path_map positional arg kaldırıldı, keyword gerekiyor
graph.add_conditional_edges(
    "data_ingestion",
    route_fn,
    path_map={    # ← keyword arg zorunlu
        "pnl":  "pnl",
        "end":  END,
    },
)
```

**Etkilenen dosyalar:**
- `backend/app/agents/orchestrator.py` — 4 adet `add_conditional_edges`
- `backend/app/agents/cto/orchestrator.py` — 1 adet
- `backend/app/agents/ceo/orchestrator.py` — 1 adet

### 2. `StateGraph.__init__` — BREAKING (0.2.x bazı sürümler)

```python
# 0.1.19
from langgraph.graph import StateGraph
graph = StateGraph(MyState)

# 0.2.x — TypedDict state type annotation zorunlu hale geldi
# Mevcut kodumuz zaten TypedDict kullanıyor (state.py) — GÜVENLI
```

### 3. `ainvoke` config — UYUMLU

```python
# 0.1.19 ve 0.2.x — aynı
result = await graph.ainvoke(
    state,
    config={"configurable": {"key": "value"}},
)
```

### 4. `END` constant — UYUMLU

```python
# Her iki versiyonda da:
from langgraph.graph import END  # END = "__end__"
```

### 5. Checkpointer API — BREAKING (kullanmıyoruz)

```python
# 0.1.x: MemorySaver, SqliteSaver (farklı import)
# 0.2.x: tamamen yeniden yazıldı
# Mevcut kodumuzda checkpointer YOK → bu sorun değil
```

---

## Migration Checklist

Upgrade öncesi adımlar:

1. **Test coverage hazırla:**
   ```bash
   pytest backend/tests/test_agents/ -q --tb=short
   # Mevcut tüm testler geçmeli
   ```

2. **Staging'de langgraph==0.2.x kur:**
   ```bash
   pip install langgraph==0.2.x  # x = son stabil sürüm
   ```

3. **`add_conditional_edges` güncelle** — tüm orchestrator'larda:
   ```python
   # ESKİ
   graph.add_conditional_edges("node", fn, {"a": "b"})
   # YENİ
   graph.add_conditional_edges("node", fn, path_map={"a": "b"})
   ```

4. **Test et:**
   ```bash
   pytest backend/tests/test_agents/test_cfo_pipeline.py -v
   pytest backend/tests/test_agents/test_cto_pipeline.py -v
   pytest backend/tests/test_agents/test_ceo_pipeline.py -v
   ```

5. **Smoke test:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/upload \
     -F "file=@demo/data/logo_tiger_2024.csv" \
     -H "Authorization: Bearer $TOKEN"
   ```

---

## Etkilenen Dosyalar (tam liste)

| Dosya | Değişiklik Türü | Öncelik |
|-------|----------------|---------|
| `agents/orchestrator.py` | `add_conditional_edges` × 4 | Yüksek |
| `agents/cto/orchestrator.py` | `add_conditional_edges` × 1 | Yüksek |
| `agents/ceo/orchestrator.py` | `add_conditional_edges` × 1 | Orta |
| `agents/cmo/orchestrator.py` | `"__end__"` string → `END` | Düşük |
| `agents/coo/orchestrator.py` | `"__end__"` string → `END` | Düşük |

---

## Neden Şimdi Geçmiyoruz?

- 0.1.19 production'da 3+ ay test edildi, stabil
- 0.2.x checkpointer API'si tamamen değişti — test suite güncelleme gerektirir
- Migration için ayrı sprint (2 gün) ayrılmalı
- Feature flag `LANGRAPH_VERSION=0.1.19|0.2.x` ile kademeli geçiş yapılabilir

---

## Hızlı Upgrade (gelecekteki sprint için)

```bash
# 1. requirements.txt'te güncelle
sed -i 's/langgraph==0.1.19/langgraph>=0.2.0,<0.3.0/' backend/requirements.txt

# 2. add_conditional_edges patchle
grep -rn "add_conditional_edges" backend/app/agents/ \
  | grep -v "path_map" \
  | awk -F: '{print $1}' | sort -u
# → Bu dosyaları manuel düzelt

# 3. Test
pytest backend/tests/test_agents/ -q
```
