#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/*
 * Invert brightness effect
 * mode 0 (full, default): simple RGB inversion, 1.0 - value
 * mode 1 (solarize): Solarize parity, min(v, 1.0 - v) per channel
 *   (PS: output = v <= 128 ? v : 255 - v, equivalent to min(v, 1-v) in 0..1)
 */

void main() {
    ivec2 texSize = textureSize(inputTex, 0);
    vec2 uv = gl_FragCoord.xy / vec2(texSize);
    vec4 color = nmTex(inputTex, uv);

    // Invert the underlying color and retain premultiplied coverage.
    if (mode == 1) {
        color.rgb = min(color.rgb, color.a - color.rgb);
    } else {
        color.rgb = color.a - color.rgb;
    }

    fragColor = color;
}
