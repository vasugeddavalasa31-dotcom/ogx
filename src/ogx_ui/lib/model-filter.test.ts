import type { Model } from "ogx-client/resources/models";
import {
  filterManagedModels,
  filterModels,
  parseModelAllowlist,
} from "./model-filter";

const models = [
  { id: "model-a" },
  { id: "model-b" },
  { id: "model-c" },
] as Model[];

describe("model filtering", () => {
  test("keeps the API model list unchanged when no allowlist is configured", () => {
    expect(parseModelAllowlist(undefined)).toEqual([]);
    expect(filterModels(models, [])).toEqual(models);
  });

  test("filters models in allowlist order", () => {
    const allowed = parseModelAllowlist(" model-c, model-a ");

    expect(filterModels(models, allowed).map(model => model.id)).toEqual([
      "model-c",
      "model-a",
    ]);
  });

  test("omits unknown model IDs", () => {
    const allowed = parseModelAllowlist("missing, model-b");

    expect(filterModels(models, allowed).map(model => model.id)).toEqual([
      "model-b",
    ]);
  });

  test("keeps only managed LLM models, dropping provider-prefixed duplicates", () => {
    const withDupes = [
      { id: "deepseek-v4-flash", custom_metadata: { model_type: "llm" } },
      {
        id: "openai/deepseek-v4-flash",
        custom_metadata: { model_type: "llm" },
      },
      { id: "deepseek-v4-pro", custom_metadata: { model_type: "llm" } },
      { id: "openai/deepseek-v4-pro", custom_metadata: { model_type: "llm" } },
      {
        id: "sentence-transformers/nomic-ai/nomic-embed-text-v1.5",
        custom_metadata: { model_type: "embedding" },
      },
      {
        id: "sentence-transformers/Qwen/Qwen3-Reranker-0.6B",
        custom_metadata: { model_type: "rerank" },
      },
    ] as unknown as Model[];

    expect(filterManagedModels(withDupes).map(model => model.id)).toEqual([
      "deepseek-v4-flash",
      "deepseek-v4-pro",
    ]);
  });

  test("keeps prefixed models that have no unprefixed alias", () => {
    const onlyPrefixed = [
      { id: "moonshotai/kimi-k2.6", custom_metadata: { model_type: "llm" } },
    ] as unknown as Model[];

    expect(filterManagedModels(onlyPrefixed).map(model => model.id)).toEqual([
      "moonshotai/kimi-k2.6",
    ]);
  });
});
