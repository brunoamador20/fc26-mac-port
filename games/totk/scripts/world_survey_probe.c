/* CPU-only: exercise real command parsing, guarded pointer traversal and frame-end request handling. */
#include "../runtime/world_survey.c"
#include <sys/wait.h>
#include <unistd.h>
static unsigned checks, moves;
_Noreturn void runtime_fail(const char *why) { fprintf(stderr, "probe runtime failure: %s\n", why); _exit(2); }
static void check(int ok, const char *why) { checks++; if (!ok) { fprintf(stderr, "FAIL: %s\n", why); exit(1); } }
static void pointer(void *base, size_t off, void *value) { memcpy((char *)base + off, &value, sizeof value); }
static void mock_force(void *actor, const float *m, uint32_t flag) {
    check(flag == 0, "normal physics move flag"); moves++;
    if (getenv("TOTK_PROBE_NEGATIVE")) return;
    float xyz[] = {m[3], m[7], m[11]}; memcpy((char *)actor + ACTOR_POS, xyz, sizeof xyz);
}
int main(void) {
    char tmp[] = "/tmp/totk-world-survey-XXXXXX";
    check(mkdtemp(tmp) != NULL, "temporary test profile");
    setenv("TOTK_SURVEY", "1", 1); setenv("TOTK_SLOT_OWNER", "codex", 1); setenv("TOTK_PROFILE_DIR", tmp, 1);
    size_t size = SCENE_SLOT + 8u; unsigned char *image = calloc(1, size); check(image != NULL, "fake main");
    const uint32_t entry[] = {0xa9bd7bfd, 0xf9000bf5, 0x910003fd, 0xa9024ff4};
    memcpy(image + FORCE_MATRIX, entry, sizeof entry);
    Module module = {.name="main", .base=image, .size=size, .text_end=FORCE_MATRIX+sizeof entry};
    runtime_survey_init(&module); survey_force = mock_force;
    check(runtime_survey_command("key 38 100\n") == 0, "other command untouched");
    check(runtime_survey_command("survey move bad nan 1 2 1\n") == 1 && !runtime_survey_pending, "NaN rejected");
    runtime_survey_command("survey move bad 0 -5000 0 1\n"); check(!runtime_survey_pending, "world bounds rejected");
    runtime_survey_command("survey move bad 1 2 3 601\n"); check(!runtime_survey_pending, "hold bounded");
    runtime_survey_command("survey pos inspect\n"); runtime_survey_tick(1); check(!runtime_survey_pending && !moves, "missing scene handled");
    unsigned char sm[0x200]={0}, scene[0x60]={0}, components[14*8]={0}, resident[0x30]={0}, links[0x70]={0}, data[0x60]={0}, actor[0x500]={0};
    pointer(image, SCENE_SLOT, sm); pointer(sm, 0x1e8, scene); int n=14; memcpy(scene+0x50,&n,4); pointer(scene,0x58,components);
    pointer(components,13*8,resident); n=1; memcpy(resident+0x20,&n,4); pointer(resident,0x28,links); pointer(links,8,data);
    pointer(data,0x40,actor); pointer(actor,0x210,"Player");
    float pos[]={1,2,3}, rot[]={1,0,0,0,1,0,0,0,1}; memcpy(actor+ACTOR_POS,pos,sizeof pos); memcpy(actor+ACTOR_ROT,rot,sizeof rot);
    check(player_actor()==(uintptr_t)actor,"resident Player resolved");
    pointer(actor,0x210,"Enemy!"); check(!player_actor(),"wrong actor name rejected"); pointer(actor,0x210,"Player");
    pointer(data,0x40,(void *)0x1234); check(!player_actor(),"unmapped actor handled without fault"); pointer(data,0x40,actor);
    runtime_survey_command("survey move small 11 12 13 2\n"); check(runtime_survey_pending && !moves,"move queued without immediate write");
    runtime_survey_tick(2); check(moves==1 && runtime_survey_pending,"hold first frame");
    runtime_survey_tick(3); check(moves==2 && !runtime_survey_pending,"hold completion");
    memcpy(pos,actor+ACTOR_POS,sizeof pos); check(pos[0]==11 && pos[1]==12 && pos[2]==13,"position actually changed");
    runtime_survey_command("survey move cancel 20 30 40 30\n"); runtime_survey_cancel_user(); runtime_survey_tick(4);
    check(moves==2 && !runtime_survey_pending,"user cancels pending movement");
    pid_t child=fork(); check(child>=0,"negative identity child");
    if(!child) { image[FORCE_MATRIX]^=1; runtime_survey_init(&module); _exit(0); }
    int status; waitpid(child,&status,0); check(WIFEXITED(status)&&WEXITSTATUS(status)==2,"wrong function identity rejected");
    free(image); rmdir(tmp); printf("world-survey CPU probe: %u checks passed\n",checks); return 0;
}
