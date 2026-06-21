#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/* Scrolls texture coordinates with wraparound. */
void main(){
  vec2 globalCoord = gl_FragCoord.xy + tileOffset;
  vec2 globalUV = globalCoord / fullResolution;
  
  globalUV.x *= aspect;
  vec2 offset = vec2(-x + time * -speedX, y + time * speedY);
  offset.x *= aspect;
  globalUV += offset;
  globalUV.x /= aspect;
  
  // Convert to local UV for sampling
  vec2 localUV = (globalUV * fullResolution - tileOffset) / vec2(textureSize(inputTex, 0));
  
  // Apply wrap mode in local UV space to constrain to tile bounds
  if (wrap == 0) {
      // mirror
      localUV = abs(mod(localUV + 1.0, 2.0) - 1.0);
  } else if (wrap == 1) {
      // repeat
      localUV = fract(localUV);
  } else {
      // clamp
      localUV = clamp(localUV, 0.0, 1.0);
  }
  
  fragColor = vec4(nmTex(inputTex, localUV).rgb, 1.0);
}
