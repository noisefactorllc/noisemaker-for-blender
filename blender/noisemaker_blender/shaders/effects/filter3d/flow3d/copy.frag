// Copy Pass - Blit source to destination (for ping-pong correction after diffuse)
// This ensures the decayed trail is in the write nm_buffer before deposit blends onto it

void main() {
    // Use actual texture size, not canvas resolution
    ivec2 texSize = textureSize(sourceTex, 0);
    vec2 uv = gl_FragCoord.xy / vec2(texSize);
    fragColor = texture(sourceTex, uv);
}
