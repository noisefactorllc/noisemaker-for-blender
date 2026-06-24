#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    vec2 uv = gl_FragCoord.xy / resolution;

    vec4 inputColor = nmTex(inputTex, uv);
    vec4 trailColor = nmTex(trailTex, uv);

    float t = inputIntensity / 100.0;
    vec4 scaledInput = inputColor * t;

    vec3 outRGB;
    float outAlpha;

    if (blendMode == 1) {
        // Alpha mode: trail stores premultiplied values (rgb = actual_color * alpha).
        // Use premultiplied OVER operator then convert to straight for output.
        outAlpha = trailColor.a + scaledInput.a * (1.0 - trailColor.a);
        vec3 outRGB_pre = trailColor.rgb + scaledInput.rgb * scaledInput.a * (1.0 - trailColor.a);
        outRGB = outAlpha > 0.0 ? outRGB_pre / outAlpha : vec3(0.0);
    } else {
        // Additive mode: trail stores additive sums; treat as pseudo-non-premultiplied.
        outAlpha = trailColor.a + scaledInput.a * (1.0 - trailColor.a);
        outRGB = outAlpha > 0.0
            ? (trailColor.rgb * trailColor.a + scaledInput.rgb * scaledInput.a * (1.0 - trailColor.a)) / outAlpha
            : vec3(0.0);
    }

    fragColor = clamp(vec4(outRGB, outAlpha), 0.0, 1.0);
}
