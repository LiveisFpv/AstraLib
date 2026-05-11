# Topical Relevance Evaluation

## Metrics

| Metric | Baseline | Citation-aware | Best rerank | Rerank delta | Percent Base-rerank |
| --- | ---: | ---: | ---: | ---: | ---: |
| MRR@10 | 0.908564 | 0.908347 | 0.919905 | +0.011340 | +1.248% |
| Precision@10 | 0.761200 | 0.769700 | 0.777900 | +0.016700 | +2.194% |
| Precision@5 | 0.806400 | 0.812600 | 0.816600 | +0.010200 | +1.265% |
| StrongPrecision@10 | 0.665700 | 0.666000 | 0.672200 | +0.006500 | +0.976% |
| StrongPrecision@5 | 0.724200 | 0.727800 | 0.730600 | +0.006400 | +0.884% |
| nDCG@10 | 0.767105 | 0.768517 | 0.778441 | +0.011336 | +1.478% |
| nDCG@5 | 0.781554 | 0.784021 | 0.791991 | +0.010437 | +1.335% |

## Rerank Runs by nDCG@10

| Rank | Run | nDCG@10 | Delta vs Baseline | Percent Base-rerank |
| ---: | --- | ---: | ---: | ---: |
| 1 | `rerank_out1_975_out2_025_alpha_0p02` | 0.778441 | +0.011336 | +1.478% |

## Parameters

```json
{
  "dataset": "OpenAlex topical relevance",
  "model": "intfloat/multilingual-e5-large",
  "weights": {
    "self": 1.0,
    "out1": 0.0,
    "in1": 0.05,
    "out2": 0.03,
    "in2": 0.025
  }, 
  "judge": {
    "base_url": "http://localhost:1234/v1",
    "model": "openai/gpt-oss-20b",
    "prompt_version": "openalex-topic-relevance-v1",
    "temperature": 0.0
  },
  "query_limit": 1000,
  "retrieval_top_k": 100,
  "candidate_top_k": 20,
  "eval_top_k": 10,
  "rerank_mode": "citation-score",
  "alpha_vals": [
    0.02
  ],
  "rerank_weights": {
    "self": 0.0,
    "out1": 0.0,
    "in1": 0.05,
    "out2": 0.03,
    "in2": 0.025
  },
  "rerank_grid": true,
  "rerank_weight_grid": "out1_975_out2_025:self=0,out1=0.975,in1=0,out2=0.025,in2=0;",
  "rerank_tune_frac": 0.7,
  "rerank_grid_metric": "nDCG@10",
  "min_topic_df": 20,
  "max_topic_df": null,
  "seed": 42
}
```

## Runtime Stats

```json
{
  "documents": 818503,
  "queries": 1000,
  "judged_pairs": 24929,
  "retrieval_top_k": 100,
  "candidate_top_k": 20,
  "eval_top_k": 10,
  "embedding_dimension": 1024,
}
```