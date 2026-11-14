FROM vllm/vllm-openai:v0.10.2

COPY start-qwen.sh /usr/local/bin/start-qwen
RUN chmod 0555 /usr/local/bin/start-qwen

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/start-qwen"]
