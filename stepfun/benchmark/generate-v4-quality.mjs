import { writeFile } from "node:fs/promises";

// Original synthetic facts and labels are frozen before any retrieval experiment.
const topics = [
  ["astronomy", "Astronomy and observation", [
    ["A lunar eclipse happens when Earth blocks sunlight from reaching the Moon.", "What event occurs when Earth blocks sunlight from the Moon?", "en"],
    ["望远镜通过收集光线观察遥远的天体。", "什么仪器收集光线来观察远处的天体？", "zh"],
    ["A spectroscope separates starlight by wavelength to study chemical composition.", "用什么方法分析星光的波长以研究恒星成分？", "cross"]
  ], ["A comet often develops a tail near the Sun.", "A planet follows an orbit around a star.", "A meteor is a streak caused by material entering an atmosphere.", "The Milky Way is a galaxy containing many stars.", "An observatory houses instruments for viewing the sky.", "A star chart maps visible constellations.", "A solar eclipse involves the Moon obscuring the Sun."]],
  ["gardening", "Gardening and plants", [
    ["Mulch conserves soil moisture by reducing evaporation around plants.", "What garden covering helps soil retain moisture?", "en"],
    ["堆肥可以将厨余和落叶转化为改良土壤的材料。", "厨余和落叶可以通过什么方式变成土壤改良材料？", "zh"],
    ["Seedlings need gradual exposure to outdoor conditions before transplanting.", "幼苗移栽前为什么需要逐渐适应室外环境？", "cross"]
  ], ["Tomatoes prefer a sunny growing location.", "Garden shears cut small branches.", "Raised beds can improve drainage.", "A trellis supports climbing beans.", "Pollinators visit flowers for nectar.", "A watering can delivers water to seedlings.", "Roots absorb water and nutrients from soil."]],
  ["networking", "Computer networking", [
    ["DNS translates a domain name into an IP address.", "Which service resolves a website name to an IP address?", "en"],
    ["路由器根据目标地址转发网络数据包。", "什么设备根据目的地址转发数据包？", "zh"],
    ["TLS encrypts traffic between a client and a server during transmission.", "客户端与服务器之间如何加密传输的数据？", "cross"]
  ], ["A switch connects devices within a local network.", "A firewall filters traffic using rules.", "A packet carries a portion of network data.", "A subnet groups addresses in a network.", "A modem connects a local network to a service provider.", "Latency measures the time taken by a network operation.", "Bandwidth describes a connection's data capacity."]],
  ["energy", "Energy systems", [
    ["A solar panel converts sunlight into electrical energy using photovoltaic cells.", "Which device converts sunlight directly into electricity?", "en"],
    ["风力发电机利用风推动叶片来产生电能。", "什么设备利用风推动叶片发电？", "zh"],
    ["A battery stores electrical energy chemically for later use.", "哪种装置通过化学方式储存电能以便以后使用？", "cross"]
  ], ["A transformer changes alternating-current voltage.", "A power meter measures electricity consumption.", "A turbine can be driven by moving water.", "An inverter converts direct current to alternating current.", "Insulation reduces heat transfer through walls.", "A fuse breaks a circuit when current is excessive.", "A grid distributes electricity to consumers."]],
  ["bicycle", "Bicycle maintenance", [
    ["A bicycle chain transfers pedaling force from the crank to the rear wheel.", "What part transfers force from pedals to the rear wheel?", "en"],
    ["自行车刹车通过摩擦减慢车轮转动。", "自行车靠什么部件摩擦车轮来减速？", "zh"],
    ["A tire pump raises air pressure inside an inner tube.", "什么工具可以提高自行车内胎的气压？", "cross"]
  ], ["A saddle supports the rider.", "A derailleur moves the chain between gears.", "Reflectors improve visibility in low light.", "Handlebars steer the front wheel.", "A spoke connects the rim to the hub.", "A helmet protects a cyclist's head.", "A bicycle bell warns nearby pedestrians."]],
  ["cooking", "Cooking methods", [
    ["Simmering cooks food in liquid kept just below a vigorous boil.", "What cooking method keeps liquid just below a rolling boil?", "en"],
    ["蒸煮利用水蒸气加热食物，而食物不必浸在水中。", "哪种烹饪方式使用水蒸气加热食物？", "zh"],
    ["A kitchen thermometer measures the internal temperature of food.", "用什么工具测量食物内部的温度？", "cross"]
  ], ["A whisk blends ingredients by hand.", "A cutting board protects a work surface.", "Roasting uses dry heat in an oven.", "A colander drains water from pasta.", "A lid covers a cooking pot.", "A grater shreds cheese or vegetables.", "Baking soda is used in some baked goods."]],
  ["music", "Music and instruments", [
    ["A metronome provides a steady beat for practicing tempo.", "What device provides a regular beat for musicians?", "en"],
    ["钢琴通过琴键控制琴槌敲击琴弦发声。", "哪种乐器的琴键控制琴槌敲击琴弦？", "zh"],
    ["A conductor guides an orchestra using gestures and timing.", "乐队演奏时谁用手势和节奏引导演奏者？", "cross"]
  ], ["A violin has strings played with a bow.", "A flute is a woodwind instrument.", "A drum makes sound through a vibrating membrane.", "Sheet music represents notes on a staff.", "A guitar can be tuned with tuning pegs.", "A choir consists of singers.", "A melody is a sequence of musical notes."]],
  ["library", "Library services", [
    ["A library catalog records titles and helps readers locate books.", "Where can a reader look up a book's location and title?", "en"],
    ["图书馆借书证用于登记读者借阅的书籍。", "读者借阅书籍时通常使用什么证件？", "zh"],
    ["A librarian can place a hold on a book that is currently on loan.", "想借的书已经被借走时，馆员可以帮读者做什么？", "cross"]
  ], ["A reading room provides space for quiet study.", "A bookshelf stores books vertically.", "A due date indicates when a loan should be returned.", "An author writes a book.", "A periodical is published in recurring issues.", "An archive preserves historical records.", "A reference desk answers research questions."]],
  ["weather", "Weather and climate", [
    ["A barometer measures atmospheric pressure.", "Which instrument measures air pressure?", "en"],
    ["雨量计用于测量一段时间内的降雨量。", "什么仪器用于测量降雨量？", "zh"],
    ["An anemometer measures the speed of the wind.", "哪种仪器测量风速？", "cross"]
  ], ["Clouds form from condensed water droplets.", "Humidity describes water vapor in the air.", "A thermometer measures temperature.", "A forecast predicts future weather.", "A rainbow appears when light is refracted in water droplets.", "Snow consists of ice crystals.", "A weather vane indicates wind direction."]],
  ["maps", "Maps and navigation", [
    ["A compass indicates direction using a magnetic needle.", "What navigation tool uses a magnetic needle to indicate direction?", "en"],
    ["地图比例尺表示地图距离和实际距离之间的关系。", "地图上什么标记表示图上距离与实际距离的关系？", "zh"],
    ["Contour lines on a map connect points of equal elevation.", "地形图上哪种线连接海拔相同的地点？", "cross"]
  ], ["A legend explains symbols used on a map.", "Latitude describes position north or south of the equator.", "Longitude describes east-west position.", "A street map displays roads and intersections.", "A route is a planned path between locations.", "A waypoint marks a position along a journey.", "A globe models the shape of Earth."]]
];

const documents = [], queries = [];
for (const [topic, title, labeled, distractors] of topics) {
  const facts = [...labeled.map(row => row[0]), ...distractors];
  facts.forEach((fact, index) => documents.push({ id: `${topic}-${index + 1}`, filename: `${topic}-${index + 1}.md`, text: `${title}. ${fact}` }));
  labeled.forEach(([, text, language], index) => queries.push({ id: `${topic}-${language}`, language, text, relevant: [`${topic}-${index + 1}.md`] }));
}
const dataset = { license: "CC0-1.0", provenance: "Original synthetic facts authored for EdgeSeek; labels fixed by construction before model evaluation.", documents, queries };
await writeFile("benchmark/v4-quality.json", JSON.stringify(dataset, null, 2) + "\n");
console.log(JSON.stringify({ documents: documents.length, queries: queries.length }));
