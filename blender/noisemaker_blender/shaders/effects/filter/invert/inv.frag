/*
 * Invert brightness effect
 * Simple RGB inversion: 1.0 - value
 */

void main() {
    vec2 globalCoord = gl_FragCoord.xy + tileOffset;
    ivec2 texSize = textureSize(inputTex, 0);
    vec2 uv = gl_FragCoord.xy / vec2(texSize);
    vec4 color = texture(inputTex, uv);

    color.rgb = 1.0 - color.rgb;

    fragColor = color;
}
