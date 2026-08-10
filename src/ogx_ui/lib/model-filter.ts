import type { Model } from "ogx-client/resources/models";

export function parseModelAllowlist(value: string | undefined): string[] {
  return (value ?? "")
    .split(",")
    .map(modelId => modelId.trim())
    .filter(Boolean);
}

export function filterModels(
  models: Model[],
  allowedModelIds: string[]
): Model[] {
  if (allowedModelIds.length === 0) {
    return models;
  }

  const modelsById = new Map(models.map(model => [model.id, model]));
  const seenModelIds = new Set<string>();

  return allowedModelIds.flatMap(modelId => {
    const model = modelsById.get(modelId);
    if (!model || seenModelIds.has(modelId)) {
      return [];
    }

    seenModelIds.add(modelId);
    return [model];
  });
}

type ManagedModelLike = {
  id: string;
  custom_metadata?: unknown;
};

/**
 * Keep only the "managed" chat models: LLM-type models, preferring the
 * unprefixed alias over provider-prefixed duplicates (e.g. keep
 * `deepseek-v4-flash`, drop `openai/deepseek-v4-flash`). Embedding and
 * rerank models are excluded so the dashboard shows exactly the models
 * enabled in the gateway registry.
 */
export function filterManagedModels<T extends ManagedModelLike>(
  models: T[]
): T[] {
  const llmModels = models.filter(m => {
    const meta = m.custom_metadata as Record<string, unknown> | undefined;
    return !meta?.model_type || meta.model_type === "llm";
  });

  const unprefixedNames = new Set(
    llmModels.filter(m => !m.id.includes("/")).map(m => m.id)
  );

  return llmModels.filter(m => {
    const slash = m.id.indexOf("/");
    if (slash <= 0) return true;
    // Drop provider-prefixed duplicates when an unprefixed alias exists.
    return !unprefixedNames.has(m.id.slice(slash + 1));
  });
}
