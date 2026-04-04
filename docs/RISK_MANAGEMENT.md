# Risk Management Systems (Risk Yönetimi Sistemleri)

Bir ticaret sisteminde kârdan çok zararı (drawdown) yönetmek kritiktir. Ajanların halüsinasyon görmesi muhtemel olduğundan risk mekanizmaları ikiye ayrılmıştır: Algoritmik (Kodla katı şekilde sağlanan) ve Bilişsel (Risk Ajanı ile yönetilen).

Bu belgede Algoritmik sistemlerin altyapısı mevcuttur.

## 📉 1. Regime Filter (Piyasa Rejimi Filtresi) & VIX
Yapay zeka modelleri ekstrem kriz koşullarını (Siyah Kuğu / Black Swan) öngöremez. Bu yüzden `risk/regime_filter.py` modülü sürekli olarak VIX endeksini (Volatility Index) tarar.
- **İşleyiş**: VIX'in SMA (Hararet) değeri izlenir. 
- Eğer VIX anlık olarak belli bir eşik değerin üzerine fırlar veya sabit olarak 40'ı geçerse, sistem rejimi `CRISIS` olarak işaretlenir.
- `halt_trading = True` döndürülür ve yapay zeka ne derse desin, **tüm işlemler koordinatör katmanında reddedilir**.

## 🛡️ 2. Trailing Stop Loss (Dinamik/İzleyen Zarar-Kes - ATR Bazlı)
Ortalama Gerçek Aralık (ATR - Average True Range), `risk/stop_loss.py` içerisinde kullanılır. Yapay zeka statik bir fiyat girerse bu fiyat genellikle piyasa spekülasyonu ile kolay temizlenen volatil bir noktaya denk gelebilir.
- **Dinamik**: Varlık lehe gittiğinde, stop price adım adım yukarı taşınır (long için).
- Aleyhe döndüğünde stop rakamı ASLA geri çekilmez.
- `Hard Stop Pct` özelliği ile her durumda portföy sermayesinin %x'inden fazlasını tek bir işlemde yakmayacak katı bir yüzde sınırlandırılması mevcuttur (Örn: %2).

## 🧮 3. Conditional Value at Risk (CVaR)
Mean-Variance (Markowitz) portföy teorilerinin yerine daha gelişmiş bir kuyruk (tail-risk) yönetimi için `risk/cvar_optimizer.py` kullanılır.
- **Neden CVaR**: Basit Value at Risk (VaR), yatırımın %95 ihtimalle en fazla kaybedeceği oranı verir ancak o %5'in sonrasında batışın ne kadar derin olduğunu bilmez. CVaR ise "Eğer batarsak, bu dibin ortalaması ne olacak" sorusunu baz alarak çoklu varlık ağırlık dağıtımlarını gerçekleştirir.

## 🎒 4. Portfolio State (Portföy Takibi)
`risk/portfolio.py` tüm Unrealized PNL ve Equity (Özvarlık) bilgilerini tutar.
Eğer algoritmik bot sistemin kârlı olduğu halde sürekli Drawdown (Max tepe değerden geri çekim) limitini aşıyorsa (`config/trading_params.yaml` içinde tanımlalı) yeni pozisyon kapatana kadar `open_position` eylemi iptal edilir.
