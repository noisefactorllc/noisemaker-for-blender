// Copy Pass - Blit grid to write nm_buffer for proper blending

void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    fragColor = texture(gridTex, uv);
}
