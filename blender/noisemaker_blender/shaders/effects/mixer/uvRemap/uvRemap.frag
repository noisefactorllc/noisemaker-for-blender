#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
float mirrorWrap(float t) {
    float m = mod(t, 2.0);
    return m > 1.0 ? 2.0 - m : m;
}

vec2 applyWrap(vec2 uv, int wrapMode) {
    if (wrapMode == 0) {
        return clamp(uv, 0.0, 1.0);
    } else if (wrapMode == 1) {
        return vec2(mirrorWrap(uv.x), mirrorWrap(uv.y));
    } else {
        return fract(uv);
    }
}

void main() {
    vec2 localUV = gl_FragCoord.xy / resolution;
    vec4 colorA = nmTex(inputTex, localUV);
    vec4 colorB = nmTex(tex, localUV);

    vec4 mapColor = (mapSource == 0) ? colorA : colorB;
    int sampleFromB = (mapSource == 0) ? 1 : 0;

    vec2 rawUV;
    if (channel == 0) {
        rawUV = mapColor.rg;
    } else if (channel == 1) {
        rawUV = vec2(mapColor.r, mapColor.b);
    } else {
        rawUV = vec2(mapColor.g, mapColor.b);
    }

    float s = scale / 100.0;
    vec2 remappedUV = rawUV * s + offset;
    remappedUV = applyWrap(remappedUV, wrap);

    vec2 sampleUV = (remappedUV * fullResolution - tileOffset) / resolution;
    sampleUV = fract(sampleUV);

    vec4 result;
    if (sampleFromB == 1) {
        result = nmTex(tex, sampleUV);
    } else {
        result = nmTex(inputTex, sampleUV);
    }

    fragColor = result;
}
