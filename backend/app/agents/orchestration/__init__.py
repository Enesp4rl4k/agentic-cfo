"""Cross-role orchestration — glue that coordinates multiple agent kernels.

Lives under app/agents/ (not app/services/) because it depends on agent
kernels; keeping it here preserves the api → agents → services layering.
"""
