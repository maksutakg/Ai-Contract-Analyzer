# Sözleşme Değerlendirme Veri Seti Etiketleme Rehberi (Paket 4)

Bu format, 20–30 gerçek sözleşmenin (kira, hizmet, iş) madde düzeyinde etiketlenmesi ve `scripts/evaluate.py` ile nicel ölçüm yapılması için tasarlanmıştır.

## JSON Yapısı (`EvalDataset`)

```json
{
  "version": "1.0",
  "contracts": [
    {
      "contract_id": "lease-001",
      "contract_type": "lease",
      "party": "tenant",
      "expected_risk_level": "high",
      "raw_text": "KONUT KİRA SÖZLEŞMESİ\nMADDE 1 - KONU\n...",
      "expected_findings": [
        {
          "clause_id": "clause-2",
          "category": "deposit_forfeiture",
          "severity": "high",
          "disadvantaged_party": "tenant",
          "statutory": true
        }
      ],
      "expected_missing_topics": ["handover", "utilities"],
      "decision_examples": [
        {
          "finding_category": "deposit_forfeiture",
          "finding_explanation": "Güvence bedeli 3 aylık kirayı aşıyor.",
          "decision_title": "Yargıtay 3. HD E. 2019/1234",
          "decision_excerpt": "...",
          "expected_grade": "relevant"
        }
      ],
      "chat_questions": [
        {
          "question": "Depozito tutarı ne kadar belirlenmiş?",
          "covered": true,
          "relevant_chunk_ids": ["clause-2", "check-lease_deposit_cap"]
        },
        {
          "question": "Sözleşmede evcil hayvanla ilgili bir hüküm var mı?",
          "covered": false,
          "relevant_chunk_ids": []
        }
      ]
    }
  ]
}
```

## Kurallar

1. **Madde kimlikleri (`clause_id`)**: `law_rag.segmentation.segment_clauses(raw_text)` çıktısındaki sıra ile eşleşmelidir (`preamble` başlangıç bloğu, ana maddeler `clause-1`, `clause-2`, ...). Emin olmak için:
   `uv run python -c "from law_rag.segmentation import segment_clauses; print([(c.id, c.title) for c in segment_clauses(open('sozlesme.txt', encoding='utf-8').read())])"`
2. **Kanuni kategoriler (`category`)**: Yalnızca `src/law_rag/categories.py` içindeki `CANONICAL_CATEGORIES` değerleri kullanılabilir:
   `cash_payment`, `deposit_forfeiture`, `termination`, `penalty_clause`, `unlawful_entry`, `eviction_undertaking`, `rent_increase`, `jurisdiction`, `data_protection`, `intellectual_property`, `force_majeure`, `payment_interest`, `liability`, `dispute_resolution`, `probation_period`, `non_compete`, `general_risk`.
3. **Sözleşme türleri ve taraflar**:
   - `lease`: `tenant` / `landlord`
   - `service`: `client` / `provider`
   - `employment`: `employee` / `employer`
4. **CRAG karar etiketleri (`expected_grade`)**: Her sözleşmeden veya Yargı MCP çıktılarından seçilen aday kararlar `relevant`, `ambiguous` veya `irrelevant` olarak işaretlenir.
5. **Sohbet soruları (`chat_questions`)**: Hem sözleşmede yanıtı bulunan (`covered: true`) hem de kapsam dışı (`covered: false`, eşik ve ret ölçümü için) sorular eklenmelidir. İlgili parça kimlikleri: `clause-N`, `finding-N`, `check-<rule_id>`, `missing-<topic>`, `rewrite-clause-N`, `decision-N`.

